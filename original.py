#!/usr/bin/env python3
"""
ppsp — Post Photoshoot Processing

The ppsp post photoshoot processing tool is for real-estate/architectural photographers who shoot 1000+ images and publish 20–30 finals online and who want an automated CLI oriented tool to help in image batch processing, and the discovery of best processing choices, to ultimately generate the final polished outputs to publish.

(Deprecated) Complete workflow for real-estate / architectural photography:
1. Lowercase rename (idempotent)
2. Generate ppsp.csv with full metadata
3. Organize into stack_XXX folders + refined filenames (old names preserved only in CSV)
4. Create labeled culling previews
5. Manual culling guidance (delete unwanted previews with eog or similar)
6. Hugin-based HDR / Focus stack fusion (raw-aware with dcraw or darktable-cli)
7. Batch enhanced JPGs from ARW files

Motivation and requirements for the project:
- Frequently I get a 1000 images from a photoshoot but ultimately I only end up publishing 10-20 of the best outputs.
- For only those 20 I want full resolution high quality data and the optimum processing parameters but these parameters are difficult to know in advance which often leads to even dozens of variants per final image.
- This tool should help minimize human time spent on this work by helping make all choices among clearly prepared options.
- It should minimize processing time by only working on downsized data during the discovery and variant generation phase to be fast.
- The tool should be stateful in that it can be interrupted but it can nonetheless resume or restart a task without much double work. However, it should accept full redo of tasks when requested.
- It should be verbose and provide elapsed-time reporting that should help the user also to estimate the time remaining.

TODO:
- The photo renaming logic should be independent and robust and callable with '-r' or '--rename' but automatically be used within this flow; If camera model or lense ID is missing from EXIF, it should ask the user to supply a default via a CLI argument
- The stack identification should rely more on ExposureCompensation logic (e.g. 0, -2, +2) rather than time gap only
- The stacks should be all named after the first photo in the sequence, so e.g. "20260416095559-m4azzz-2501-stack" instead of e.g. stack_123
- The stack name for each photo should be added into a column (StackName) in the CSV; Note that all CSVs should by default be tab separated.
- After culling and aligned TIFF generation, the script should
  - 1) generate very small (1/8th of the original size) of the aligned TIFFs and based on those generate many enfuse and hdr-luminance-cli variants (favor processing speed over quality);
    The tool should have many variant ideas built in and ranked but the user could supply a variants level to ask for more or less variants (--variants some/many/all);
    The tool should by default assume that dcraw tool accepts -h to downsize pixel count to 25% which is good but with "--fast" it should convert the tiffs further down to 1/8th of the original size
  - 2) create a collage version 3840x3840 collage that contains on rows 1-3 downsized versions of the original JPGs, enfuse variants, and hdr-luminance-cli variants with variant name as in-image labels
  - 3) create a stack CSV asking which versions (from the enfuse and hdr variants) to recreate in full resolution and quality for each stack
  - 4) after user has confirmed having finished editing the CSV, it should read it and execute the recreation, and then use convert with a parameter variations like
      neutral: TODO
      warm: TODO
      devivid1: -colorspace sRGB -despeckle -sigmoidal-contrast 3,50% -brightness-contrast 7x-5 -modulate 100,125,100 -unsharp 0x1+0.8+0.05
      devivid2: -colorspace sRGB -despeckle -sigmoidal-contrast 4,45% -brightness-contrast 12x-8 -modulate 100,118,100 -unsharp 0x1.2+0.6+0.05
    and -resize "2048x2048>" -quality "80" -strip
    Again it should take the user supplied variants flags into consideration.
    to make images that could be immediately published online.
  - 5) Then it should make an out_full and out_web directories to which it should copy the full quality variants and their web quality finalizations.
- The file naming should always follow the logic YYYYMMDDHHMMSS-CCC[LLL]-NNNN-[variant].[ext] where variant is a simple letter (a-z) for the original JPGs by the camera from the same camera model, lense serial and second, but other variants of the same image should be named variant1, variant2 and so on.
  Since many variants are a combination of different processing choices, they should be evident: For example z100-v5selective3-fattal-devivid2-web or z25-v1natural-mantiuk06-neutral-web
- The flag "--recreate FILE1 FILE2 ..." should allow the user to give the tool as an argument properly named photo file names (with the previously mentioned variant labeling) and ask it to recreate them; From the file name it should determine the file or stack the image should be generated from, and the requested processing sequence (variant label flow); At every step it should check whether a processing output is actually already available to avoid redoing work unnecessarily (unless --redo is given)
- Cleanup of intermediate processing data (e.g. TIFFs) should only be done when the user requests "--cleanup".
- The whole tool should be made into a proper pip installable package and tool with tests; The current inp folder in this repo provides data for testing.
- Write a full README.md that describes the tool's motivation, features, usage and CLI argument possibilities comprehensively
- Add a proper intro and usage description also to the tool's "--help"
- The tool should be written with good structure such that many functions and perhaps even a class for a photo and stack file is used along with helper functions to make the implementation easily understandable and concise
- All classes, functions and processig steps should have concise docstrings and comments with some argumentation
- It is very possible that later there will be many additions and improvements and extensions to the tool and thus it is beneficial if the design and structuring is clear, robust and extensible
- Standard python libraries should be preferred, but the specific Linux CLI tools can be expected; It is expected that the user already uses them and this Python script is sort of an "advanced convenience wrapper".
"""

import os, csv, shutil, argparse, subprocess, logging, sys, re, time, glob
from datetime import datetime
from pathlib import Path

# ====================== CONFIG ======================
LOG_FILE = "ppsp.log"
DEFAULT_CSV = "ppsp.csv"
DEFAULT_CULL_DIR = "./cull"
DEFAULT_GAP = 30.0
PREVIEW_SIZE = "1920x1080"
PREVIEW_QUALITY = 55
ANNOTATE_FONT = "Liberation-Sans"
ANNOTATE_POINTSIZE = 26
# ===================================================

def setup_logging(verbose=False):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=[logging.FileHandler(LOG_FILE, 'a', 'utf-8'), logging.StreamHandler()])
    logging.info("="*80)
    logging.info("🚀 ppsp started")

def run_command(cmd, desc, check=True, shell=False):
    scmd = ' '.join(map(str, cmd)) if not shell else cmd
    logging.info(f"Running: {scmd}  # {desc}")
    start_time = time.perf_counter()
    rv = None
    try:
        rv = r = subprocess.run(cmd, capture_output=True, text=True, check=check, shell=shell)
        if r.stdout: logging.debug(r.stdout.strip())
        if r.stderr: logging.warning(r.stderr.strip())
        duration = time.perf_counter() - start_time
        if duration > 4:
            logging.info(f"  {duration:.1f}s taken by command {scmd}  # {desc}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed: {e}")
        if check: raise
    return rv

def get_raw_converter():
    if shutil.which("dcraw"): return "dcraw" # better Sony ARW compatibility
    if shutil.which("darktable-cli"): return "darktable-cli"
    return None

def create_jpg_from_arw(arw_path: Path, jpg_path: Path, size=None, quality=80, fast=False):
    """High-quality ARW → JPG conversion optimized for real-estate/architectural work."""
    if jpg_path.exists():
        return True

    conv = get_raw_converter()
    if not conv:
        logging.warning(f"No raw converter for {arw_path.name}")
        return

    logging.info(f"Creating high-quality JPG from {arw_path.name}")

    if conv == "dcraw":
        cmd = f"dcraw -4 -c -w -H 2 -q {'0' if fast else '3'} \"{arw_path}\" | convert - " #  -h
        #cmd += "-limit memory 12GB -limit map 12GB "   # prevent cache exhaustion
        cmd += "-colorspace sRGB -sigmoidal-contrast 4,50% -unsharp 0x1.2+1.5+0.05 "
        if size:
            cmd += f"-resize {size}^ -gravity center -crop {size}+0+0 "
        cmd += f"-quality {quality} \"{jpg_path}\""
        run_command(cmd, "dcraw + ImageMagick processing", shell=True)
    else:  # darktable-cli
        run_command(["darktable-cli", str(arw_path), str(jpg_path)], "darktable-cli export")
        if size:
            run_command(["mogrify", "-resize", f"{size}^", "-gravity", "center", "-crop", f"{size}+0+0", "-quality", str(quality), str(jpg_path)], "Resize")

    # Copy full EXIF
    run_command(["exiftool", "-TagsFromFile", str(arw_path), "-all:all", "-overwrite_original", str(jpg_path)],
                "Copy EXIF", check=False)
    return jpg_path.exists()

def compute_refined_name(row, orig_name, target_dir):
    ts = row.get('_ts')
    date_str = ts.strftime("%Y%m%d%H%M%S") if ts and ts != datetime.min else "00000000000000"
    model = str(row.get('Model', '')).strip()
    ccc = model[-3:].lower() if len(model) >= 3 else "zzz"
    lll_src = str(row.get('SerialNumber', '') or row.get('LensID', '')).strip()
    lll = lll_src[-3:].lower() if len(lll_src) >= 3 else "zzz"
    digits = re.findall(r'\d+', orig_name)
    nnnn = digits[-1][-4:] if digits else "0000"
    base = f"{date_str}-{ccc}{lll}-{nnnn}"
    ext = Path(orig_name).suffix.lower()
    letter = 'a'
    while (target_dir / f"{base}-{letter}{ext}").exists():
        letter = chr(ord(letter) + 1)
    return f"{base}-{letter}{ext}"

def get_exposure_comp(fpath):
    try:
        r = subprocess.run(["exiftool", "-ExposureCompensation", "-s3", str(fpath)], capture_output=True, text=True, check=False)
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except: return 0.0

def process_stack_hugin(stack_dir: Path, force=False):
    """Generate five enfuse variants for HDR stacks + one for focus stacks."""
    if not stack_dir.is_dir() or not stack_dir.name.startswith("stack_"):
        return

    arw_files = sorted(stack_dir.glob("*.arw"))
    jpg_files = sorted(stack_dir.glob("*.jpg"))
    image_files = arw_files if arw_files else jpg_files
    use_raw = bool(arw_files)

    if len(image_files) < 2:
        logging.info(f"⏭️  Skipping {stack_dir.name} – fewer than 2 images")
        return

    exps = [get_exposure_comp(f) for f in image_files]
    is_hdr = len({round(e, 1) for e in exps}) > 1
    stack_type = "HDR" if is_hdr else "Focus"

    logging.info(f"🔬 Processing {stack_dir.name} as {stack_type} stack ({len(image_files)} images)")

    start_time = time.perf_counter()

    if use_raw:
        logging.info("   Converting ARW → 16-bit TIFF...")
        tiff_files = []
        rawconv = get_raw_converter()
        for arw in arw_files:
            # dcraw -T always writes next to the ARW with .tif extension
            tif = arw.with_suffix(".tif")

            if not tif.exists() or force:
                if rawconv == 'dcraw':
                    # Improved dcraw call: force unsigned 16-bit + better metadata
                    run_command(["dcraw", "-T", "-4", "-w", "-q", "3", '-4', "-M", str(arw)], f"dcraw TIFF for {arw.name}") # , "-h"
                    dcraw_tif = arw.with_suffix(".tiff")
                    if dcraw_tif.exists():
                        dcraw_tif.rename(tif)
                else:
                    run_command(["darktable-cli", str(arw), str(tif)], "darktable TIFF")

            if tif.exists():
                # Rename to a clean name inside the stack folder for alignment
                clean_tif = stack_dir / f"{arw.stem}_aligned.tif"
                tif.rename(clean_tif)
                tiff_files.append(clean_tif)
            else:
                logging.error(f"Failed to produce TIFF for {arw.name}")
                return
        align_inputs = tiff_files
    else:
        align_inputs = image_files

    # Align images
    align_prefix = stack_dir / "aligned_"
    align_cmd = ["align_image_stack", "-a", str(align_prefix), "-v"]
    if not is_hdr:
        align_cmd.append("-m")
    align_cmd.extend([str(p) for p in align_inputs])
    run_command(align_cmd, f"Aligning {stack_type} stack")

    aligned_tiffs = sorted(stack_dir.glob("aligned_*.tif"))
    if not aligned_tiffs:
        logging.error("❌ Alignment failed")
        return

    if is_hdr:
        # A few useful enfuse variants for architectural HDR
        variants = [
            ("v1natural",      ["--exposure-weight=1.0", "--saturation-weight=0.2", "--contrast-weight=0.2"]), # indeed quite natural
#            ("v2conservative", ["--exposure-weight=0.8", "--saturation-weight=0.2", "--contrast-weight=0.3"]), # very slightly darker
            ("v3selective1",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.4", "--exposure-width=0.9"]),  # SHIT due to negative effects
#            ("v4selective2",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.3", "--exposure-width=0.7", "--hard-mask"]), # bright
            ("v5selective3",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.5", "--exposure-width=0.5", "--hard-mask"]), # very good
            ("v6selective4",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.6", "--exposure-width=0.4", "--hard-mask"]), # best
#            ("v7selective5",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.8", "--exposure-width=0.3", "--hard-mask"]), # about the same
            ("v8selective6",   ["--exposure-weight=1.0", "--saturation-weight=0.1", "--contrast-weight=0.8", "--exposure-width=0.2", "--hard-mask"]), # worse
            ("v9contrast",     ["--exposure-weight=0.6", "--saturation-weight=0.1", "--contrast-weight=0.8", "--hard-mask"]),
        ]

        lumin_tif = None

        for label, extra_params in variants:
            fused_name = f"{stack_dir.name}_enfuse_{label}.jpg"
            fused_path = stack_dir / fused_name

            if fused_path.exists() and not force:
                logging.info(f"⏭️  Skipping existing variant: {fused_name}")
                continue

            temp_tif = stack_dir / f"temp_{label}.tif"
            cmd = ["enfuse", "-o", str(temp_tif), "--compression=none"] + extra_params
            cmd.extend([str(t) for t in aligned_tiffs])
            run_command(cmd, f"Enfuse variant: {label}")

            # Final controlled conversion from 16-bit TIFF → JPEG (prevents cache exhaustion)
            if temp_tif.exists():
                run_command([
                    "convert", str(temp_tif),
                    "-limit", "memory", "8GB", "-limit", "map", "8GB",
                    "-colorspace", "sRGB",
                    "-sigmoidal-contrast", "6,45%",           # natural roll-off
                    #"-unsharp", "0x0.8+0.8+0.05",             # very gentle sharpening only
                    "-unsharp", "0x1.2+1.5+0.05",             # sharpening
                    "-quality", "80",
                    str(fused_path)
                ], f"Convert {label} variant to JPEG")
                # Save a specific variant as 16-bit TIFF for Luminance HDR
                if label == "v5selective3":
                    lumin_tif = stack_dir / f"{stack_dir.name}_enfuse_{label}_16bit.tif"
                    shutil.copy2(temp_tif, lumin_tif)
                    logging.info(f"Saved 16-bit TIFF for Luminance HDR: {lumin_tif.name}")
                temp_tif.unlink(missing_ok=True)

            logging.info(f"✅ Created variant: {fused_name}")

        # === Automatic tone-mapping on the selected enfuse ===
        if lumin_tif and lumin_tif.exists():
            # A few useful enfuse variants for architectural HDR
            variants = [
                ("mantiuk06",     ["--tmo", "mantiuk06"]),
                ("mantiuk08",     ["--tmo", "mantiuk08"]),
                ("ferradans",     ["--tmo", "ferradans"]),
                ("fattal",        ["--tmo", "fattal"]),
                ("ferwerda",      ["--tmo", "ferwerda"]),
            ]
            for label, extra_params in variants:
                tonemapped_name = f"{stack_dir.name}_tonemapped_{label}.jpg"
                tonemapped_path = stack_dir / tonemapped_name

                if not tonemapped_path.exists() or force:
                    logging.info(f"Applying {label} tone-mapping via luminance-hdr-cli...")
                    run_command(["luminance-hdr-cli", "-l", str(lumin_tif), "-o", str(tonemapped_path)]
                         + extra_params
                         + ["-q", "80"], f"Luminance HDR {label} tone-mapping")

                    logging.info(f"✅ Created tonemapped version: {tonemapped_name}")
                else:
                    logging.info(f"⏭️  Tonemapped version already exists: {tonemapped_name}")

    else:
        # Simple focus stack (one variant)
        fused_path = stack_dir / f"{stack_dir.name}_enfuse_focus.jpg"
        if fused_path.exists() and not force:
            return
        temp_tif = stack_dir / "temp_focus.tif"
        cmd = ["enfuse", "-o", str(temp_tif), "--compression=none",
               "--exposure-weight=0", "--saturation-weight=0", "--contrast-weight=1",
               "--hard-mask", "--contrast-window-size=9"]
        cmd.extend([str(t) for t in aligned_tiffs])
        run_command(cmd, "Enfuse focus stack")
        if temp_tif.exists():
            run_command(["convert", str(temp_tif), "-colorspace", "sRGB", "-unsharp", "0x0.8+0.8+0.05", "-quality", "95", str(fused_path)],
                        "Convert focus variant to JPEG")
            temp_tif.unlink(missing_ok=True)

    # Cleanup temporary files
    for t in aligned_tiffs:
        t.unlink(missing_ok=True)
    if use_raw:
        for t in tiff_files:
            t.unlink(missing_ok=True)

    duration = time.perf_counter() - start_time
    logging.info(f"✅ Finished processing {stack_dir.name} in {duration:.1f}s")

    # Copy EXIF from middle image
    middle_img = image_files[len(image_files) // 2]
    run_command(["exiftool", "-TagsFromFile", str(middle_img), "-all:all", "-overwrite_original", str(fused_path)],
                "Copying EXIF to fused result", check=False)

    duration = time.perf_counter() - start_time
    logging.info(f"✅ Fused {stack_type} stack saved: {fused_name} (took {duration:.1f}s)")

def export_fused_results(source_dir: Path, force=False):
    """Copy fused images to out-fq and create Full-HD low-quality versions in out-lq."""
    fq_dir = source_dir / "out-fq"
    lq_dir = source_dir / "out-lq"
    fq_dir.mkdir(exist_ok=True)
    lq_dir.mkdir(exist_ok=True)

    fused_files = list(source_dir.glob("stack_*/stack_*_fused_*.jpg"))
    logging.info(f"Exporting {len(fused_files)} fused images...")

    for fused in fused_files:
        # Copy full quality to out-fq
        dest_fq = fq_dir / fused.name
        if not dest_fq.exists() or force:
            shutil.copy2(fused, dest_fq)
            logging.debug(f"Copied to out-fq: {fused.name}")

        # Create Full-HD (1920px wide) quality 60 version in out-lq
        dest_lq = lq_dir / fused.name
        if not dest_lq.exists() or force:
            run_command([
                "convert", str(fused),
                "-resize", "1920x1920>",      # Full HD, preserve aspect ratio
                "-quality", "60",
                str(dest_lq)
            ], f"Creating LQ version of {fused.name}")
            logging.debug(f"Created LQ version: {dest_lq.name}")

    logging.info(f"Export completed → out-fq ({len(list(fq_dir.glob('*.jpg')))} files) and out-lq")

def main():
    parser = argparse.ArgumentParser(description="ppsp — Post Photoshoot Processing")
    parser.add_argument("--source", default=".", help="Source directory")
    parser.add_argument("--cull-dir", default=DEFAULT_CULL_DIR)
    parser.add_argument("--gap", type=float, default=DEFAULT_GAP)
    parser.add_argument("-b", "--batch", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--process-stacks", action="store_true")
    parser.add_argument("--process-stack")
    parser.add_argument("--enhance-arws", action="store_true")
    parser.add_argument("--enhance-arw")
    args = parser.parse_args()
    setup_logging(args.verbose)

    src = Path(args.source).resolve()
    cull = Path(args.cull_dir).resolve()
    csv_path = src / DEFAULT_CSV

    interactive = not args.batch

    # TARGETED MODES
    if any([args.process_stacks, args.process_stack, args.enhance_arws, args.enhance_arw]):
        if args.process_stacks or args.process_stack:
            for d in (sorted(src.glob("stack_*/")) if args.process_stacks else [Path(args.process_stack)]):
                process_stack_hugin(d, args.force)
        if args.enhance_arws or args.enhance_arw:
            arws = list(src.glob("**/*.arw")) if args.enhance_arws else [Path(args.enhance_arw)]
            for a in arws:
                enhanced = a.with_name(a.stem + "_enhanced.jpg")
                create_jpg_from_arw(a, enhanced, quality=90)
        return

    # FULL WORKFLOW
    logging.info("\n=== FULL WORKFLOW ===")

    # STEP 1: Lowercase
    start = time.perf_counter()
    renamed = sum(1 for f in src.iterdir() if f.is_file() and f.rename(f.with_name(f.name.lower())) if f.name != f.name.lower())
    logging.info(f"Renamed {renamed} files ({time.perf_counter()-start:.1f}s)")

    # STEP 2: CSV generation + GLOBAL refined renaming + clean timestamp
    logging.info("\n=== STEP 2: Creating ppsp.csv + applying refined filenames globally ===")
    start = time.perf_counter()

    rows = []
    if not csv_path.exists() or args.force:
        files = glob.glob(str(src / "*.jpg")) + glob.glob(str(src / "*.arw"))
        if not files:
            logging.error("No image files found.")
            sys.exit(1)

        # Create initial CSV
        cmd = [
            "exiftool", "-csv", "-r", "-f",
            "-FileName", "-FileSize", "-DateTimeOriginal", "-SubSecTimeOriginal",
            "-Model", "-SerialNumber", "-LensID",
            "-ExposureTime", "-FNumber", "-ISO", "-ExposureCompensation"
        ] + files

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        csv_path.write_text(result.stdout, encoding='utf-8')

        # === GLOBAL REFINED RENAMING + clean ===
        logging.info("Applying refined filenames globally...")
        with open(csv_path, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                # Robust timestamp → YYYYMMDDHHMMSS
                dt_str = row.get('DateTimeOriginal', '').strip()
                subsec = row.get('SubSecTimeOriginal', '').strip()
                row['_ts'] = None
                try:
                    if dt_str:
                        # Parse and format to clean string for filename
                        if subsec.isdigit():
                            full = f"{dt_str}.{subsec.ljust(6, '0')}"
                            ts_obj = datetime.strptime(full, '%Y:%m:%d %H:%M:%S.%f')
                        else:
                            ts_obj = datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
                        row['_ts'] = ts_obj
                except Exception as e:
                    logging.warning(f"Timestamp parse failed for {row.get('FileName')}: {e}")

                fname = row.get('FileName', '').strip()
                if fname and fname != '-':
                    orig_path = src / fname
                    if orig_path.exists():
                        refined_name = compute_refined_name(row, fname, src)
                        if orig_path != (src / refined_name):
                            orig_path.rename(src / refined_name)
                            row['FileName'] = refined_name
                            logging.debug(f"Renamed: {fname} → {refined_name}")
                rows.append(row)

        rows = sorted(rows, key=lambda x: x.get('FileName', ''))

        # Rewrite clean CSV (FileName = refined, SourceFile = old path)
        fieldnames = ['FileName', 'FileSize',
                      'DateTimeOriginal', 'SubSecTimeOriginal', 'Model', 'SerialNumber',
                      'LensID', 'ExposureTime', 'FNumber', 'ISO', 'ExposureCompensation', 'SourceFile']
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

        logging.info(f"Global renaming complete. CSV rewritten.")
    else:
        logging.info("Using existing ppsp.csv")
        with open(csv_path, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                row['_ts'] = datetime.strptime(row.get('DateTimeOriginal', '').strip(), '%Y:%m:%d %H:%M:%S')
                rows.append(row)

    logging.info(f"STEP 2 completed in {time.perf_counter()-start:.1f}s")

    # STEP 3: Stack organization (files already globally renamed)
    start = time.perf_counter()
    for row in rows:
        row['_exp'] = float(row.get('ExposureCompensation', 0) or 0)

    cull.mkdir(exist_ok=True)
    stack_id = 0
    last_t = last_e = None
    current = []

    def process_stack(files, sid):
        nonlocal stack_id
        folder = src / f"stack_{sid:03d}"
        folder.mkdir(exist_ok=True)

        # Move already-renamed files into stack folder
        for r in files:
            fname = r.get('FileName', '')
            if not fname:
                continue
            src_file = src / fname
            if src_file.exists() and not (folder / fname).exists():
                shutil.move(str(src_file), folder)
                logging.debug(f"Moved {fname} → {folder.name}")

        # Select representative (prefer JPG, then 0 EV, then middle)
        rep = next((r for r in files if r['FileName'].lower().endswith('.jpg') and abs(r['_exp']) < 0.01), None)
        if not rep:
            rep = next((r for r in files if r['FileName'].lower().endswith('.jpg')), None)
        if not rep:
            rep = next((r for r in files if abs(r['_exp']) < 0.01), files[len(files)//2])

        # Create culling preview from the renamed file
        preview_name = f"stack_{sid:03d}_count_{len(files)}.jpg"
        preview_dest = cull / preview_name
        rep_path = folder / rep['FileName']

        if preview_dest.exists():
            logging.debug(f"Preview already exists: {preview_name}")
        elif rep_path.suffix.lower() == ".jpg":
            shutil.copy2(rep_path, preview_dest)
        else:
            create_jpg_from_arw(rep_path, preview_dest, size=PREVIEW_SIZE, quality=PREVIEW_QUALITY, fast=True)

        logging.info(f"✅ Processed {folder.name} ({len(files)} images) — preview ready")

    # OOOOOO
    for row in rows:
        is_new = last_t is None or (row['_ts'] - last_t).total_seconds() > args.gap or (abs(row['_exp']) < 0.01 and abs(last_e) >= 0.01)
        if is_new and current:
            process_stack(current, stack_id)
            current = []
        if is_new: stack_id += 1
        current.append(row)
        last_t, last_e = row['_ts'], row['_exp']
    if current: process_stack(current, stack_id)
    logging.info(f"Stacks done in {time.perf_counter()-start:.1f}s")

    # STEP 4: Resize previews to 1920x1080 + add visible labels
    logging.info("\n=== STEP 4: Resizing + labeling culling previews ===")
    preview_files = list(cull.glob("*.jpg"))
    if preview_files and (args.batch or input(f"Resize + label {len(preview_files)} previews? [Y/n]: ").strip().lower() != 'n'):
        start = time.perf_counter()

        # Force resize first so the label is large and readable
        run_command([
            "mogrify", "-resize", f"{PREVIEW_SIZE}^", "-gravity", "center",
            #"-crop", f"{PREVIEW_SIZE}+0+0",
            "+repage", "-quality", str(PREVIEW_QUALITY)
        ] + [str(p) for p in preview_files], "Resize previews to 1920x1080")

        # Then add label
        run_command([
            "mogrify", "-font", ANNOTATE_FONT, "-fill", "white", "-undercolor", "#00000080",
            "-pointsize", str(ANNOTATE_POINTSIZE), "-gravity", "NorthEast", "-annotate", "+10+10", "%t"
        ] + [str(p) for p in preview_files], "Add filename labels")

        logging.info(f"✅ Previews resized + labeled in {cull} ({time.perf_counter()-start:.1f}s)")
    else:
        logging.info("Skipping preview labeling.")

    # STEP 5: Manual culling reminder + cleanup
    logging.info("\n" + "="*60)
    logging.info("🖐️ MANUAL CULLING – delete unwanted previews in:")
    logging.info(f"    eog {cull} &")
    logging.info("="*60)
    if args.batch or input("Run cleanup of rejected stacks? [y/N]: ").lower() == 'y':
        for d in src.glob("stack_*/"):
            num = d.name.split('_')[1]
            if not list(cull.glob(f"stack_{num}_*.jpg")):
                shutil.rmtree(d, ignore_errors=True)
                logging.info(f"🗑️ Removed {d.name}")

    # STEP 6
    if args.batch or input("Process stacks with Hugin? [Y/n]: ").lower().strip() != 'n':
        for d in sorted(src.glob("stack_*/")): process_stack_hugin(d, args.force)

    # STEP 7
    if args.batch or input("Create _enhanced.jpg from all ARWs? [Y/n]: ").lower().strip() != 'n':
        for arw in src.glob("**/*.arw"):
            create_jpg_from_arw(arw, arw.with_name(arw.stem + "_enhanced.jpg"), quality=80)

    # STEP 8: Final export
    if args.batch or input("Export fused results to out-fq / out-lq? [Y/n]: ").strip().lower().strip() != 'n':
        export_fused_results(src, args.force)

    logging.info("\n🎉 ppsp completed! Log: ppsp.log")
    logging.info(f"Refined files in stack_ folders • Culling: {cull}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.warning("Interrupted")
        sys.exit(130)
    except Exception as e:
        logging.exception("Error")
        sys.exit(1)
