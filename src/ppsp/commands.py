"""One cmd_* function per CLI step — see DESIGN.md § CLI-to-function mapping."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import List, Optional

from .export import export_variants
from .models import ChainSpec, StackType, parse_chain
from .processing import (
    apply_grading,
    convert_raw_to_tiff,
    create_jpg_from_arw,
    process_stack,
    run_enfuse,
    run_tmo,
    align_stack,
)
from .rename import (
    compute_refined_name,
    extract_exif,
    parse_timestamp,
    read_photos_csv,
    write_photos_csv,
)
from .stacking import (
    detect_stack_boundaries,
    detect_stack_type,
    make_stack_name,
    photos_from_csv_rows,
)
from .util import get_raw_converter, run_command
from .variants import GRADING_PRESETS, TMO_VARIANTS, expand_variants

_PHOTOS_CSV = "ppsp_photos.csv"
_GENERATE_CSV = "ppsp_generate.csv"


# ---------------------------------------------------------------------------
# Step 1
# ---------------------------------------------------------------------------


def cmd_rename(
    files: List[Path],
    source: Path,
    default_model: str = "",
    default_lens: str = "",
    redo: bool = False,
) -> None:
    """Rename files to canonical scheme and write ppsp_photos.csv — see README.md § Step 1."""
    if not files:
        files = (
            list(source.glob("*.arw"))
            + list(source.glob("*.ARW"))
            + list(source.glob("*.jpg"))
            + list(source.glob("*.JPG"))
        )
    if not files:
        logging.warning("No files found under %s", source)
        return

    rows = extract_exif(files)
    if not rows:
        logging.error("exiftool returned no rows")
        return

    renamed = 0
    skipped = 0
    for row in rows:
        orig_name = row.get("SourceFile", row.get("FileName", "")).strip()
        if not orig_name:
            continue
        orig_path = Path(orig_name)
        if not orig_path.is_absolute():
            orig_path = source / orig_path.name

        ts = parse_timestamp(
            row.get("DateTimeOriginal", ""),
            row.get("SubSecTimeOriginal", ""),
        )
        model = row.get("Model", "").strip()
        lens = (row.get("LensID", "") or row.get("SerialNumber", "")).strip()

        new_name = compute_refined_name(
            ts, model, lens, orig_path.name, source,
            default_model=default_model, default_lens=default_lens,
        )
        new_path = source / new_name

        row["SourceFile"] = orig_path.name

        if orig_path.name == new_name:
            row["FileName"] = new_name
            skipped += 1
            continue

        if orig_path.exists() and not new_path.exists():
            orig_path.rename(new_path)
            renamed += 1
        elif not orig_path.exists() and new_path.exists():
            pass  # already renamed
        elif orig_path.exists() and new_path.exists() and redo:
            orig_path.rename(new_path)
            renamed += 1

        row["FileName"] = new_name

    rows.sort(key=lambda r: r.get("FileName", ""))

    # Ensure StackName column exists (empty at this stage)
    for row in rows:
        row.setdefault("StackName", "")

    csv_path = source / _PHOTOS_CSV
    _write_csv_with_order(rows, csv_path)
    logging.info("Renamed %d files, %d already canonical. CSV: %s", renamed, skipped, csv_path)


def _write_csv_with_order(rows: List[dict], csv_path: Path) -> None:
    """Write CSV with a fixed column order matching ppsp_photos.csv spec."""
    ordered_cols = [
        "FileName", "SourceFile", "FileSize",
        "DateTimeOriginal", "SubSecTimeOriginal",
        "Model", "SerialNumber", "LensID",
        "ExposureTime", "FNumber", "ISO", "ExposureCompensation",
        "FocalLength", "WhiteBalance",
        "StackName",
    ]
    # Merge with any extra columns from exiftool
    all_keys: List[str] = list(ordered_cols)
    for row in rows:
        for k in row:
            if k not in all_keys:
                all_keys.append(k)
    import csv as _csv
    import io
    buf = io.StringIO()
    writer = _csv.DictWriter(
        buf, fieldnames=all_keys, delimiter="\t", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)
    csv_path.write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 2
# ---------------------------------------------------------------------------


def cmd_stacks_organize(
    files: List[Path],
    source: Path,
    gap: float = 30.0,
    redo: bool = False,
) -> None:
    """Group photos into per-stack folders and update ppsp_photos.csv — see README.md § Step 2."""
    csv_path = source / _PHOTOS_CSV
    if not csv_path.exists():
        logging.info("ppsp_photos.csv not found, running rename first")
        cmd_rename(files, source, redo=redo)

    rows = read_photos_csv(csv_path)
    if not rows:
        logging.error("No rows in %s", csv_path)
        return

    photos = photos_from_csv_rows(rows, source)
    if not photos:
        logging.error("No photos loaded from CSV")
        return

    groups = detect_stack_boundaries(photos, gap=gap)
    logging.info("Detected %d stacks from %d photos", len(groups), len(photos))

    # Build filename → row lookup
    row_by_filename = {r.get("FileName", ""): r for r in rows}

    for group in groups:
        stack_name = make_stack_name(group[0])
        stack_dir = source / stack_name
        stack_dir.mkdir(exist_ok=True)

        for photo in group:
            src_path = photo.path
            dst_path = stack_dir / photo.filename
            if src_path.exists() and not dst_path.exists():
                shutil.move(str(src_path), str(dst_path))
            # Update path on photo object
            photo.path = dst_path

            row = row_by_filename.get(photo.filename)
            if row is not None:
                row["StackName"] = stack_name

    rows.sort(key=lambda r: r.get("FileName", ""))
    _write_csv_with_order(rows, csv_path)
    logging.info("Stack organization complete. Updated %s", csv_path)


# ---------------------------------------------------------------------------
# Step 3
# ---------------------------------------------------------------------------


def cmd_stacks_cull(source: Path, quality: int = 80, redo: bool = False) -> None:
    """Generate labeled culling previews in cull/ — see README.md § Step 3."""
    cull_dir = source / "cull"
    cull_dir.mkdir(exist_ok=True)

    stack_dirs = sorted(d for d in source.iterdir() if d.is_dir() and d.name.endswith("-stack"))
    if not stack_dirs:
        logging.warning("No stack directories found under %s", source)
        return

    csv_path = source / _PHOTOS_CSV
    rows = read_photos_csv(csv_path) if csv_path.exists() else []
    rows_by_stack: dict = {}
    for row in rows:
        sn = row.get("StackName", "")
        rows_by_stack.setdefault(sn, []).append(row)

    raw_converter = get_raw_converter()

    for stack_dir in stack_dirs:
        stack_name = stack_dir.name
        count = len(list(stack_dir.iterdir()))
        preview_path = cull_dir / f"{stack_name}_count{count}.jpg"
        if preview_path.exists() and not redo:
            continue

        stack_rows = rows_by_stack.get(stack_name, [])
        rep_path = _select_representative(stack_dir, stack_rows)
        if rep_path is None:
            logging.warning("No representative found for %s", stack_name)
            continue

        if rep_path.suffix.lower() in (".arw", ".raw", ".cr2", ".nef", ".dng"):
            if raw_converter is None:
                logging.warning("No raw converter for %s", rep_path.name)
                continue
            tmp_jpg = cull_dir / f"_tmp_{stack_name}.jpg"
            from .processing import convert_raw_to_tiff
            # Fast path: derive JPG via dcraw pipeline
            if raw_converter == "dcraw":
                pipeline = (
                    f'dcraw -4 -c -w -q 0 -h "{rep_path}" | '
                    f'convert - -resize 1920x1080 -quality 55 "{tmp_jpg}"'
                )
                run_command(pipeline, "cull preview from ARW", shell=True, check=False)
            else:
                run_command(
                    ["darktable-cli", str(rep_path), str(tmp_jpg)],
                    "cull preview from ARW",
                    check=False,
                )
            if tmp_jpg.exists():
                tmp_jpg.rename(preview_path)
        else:
            run_command(
                [
                    "convert", str(rep_path),
                    "-resize", "1920x1080",
                    "-quality", "55",
                    str(preview_path),
                ],
                "cull preview resize",
                check=False,
            )

        if preview_path.exists():
            run_command(
                [
                    "mogrify",
                    "-font", "Liberation-Sans",
                    "-fill", "white",
                    "-undercolor", "#00000080",
                    "-pointsize", "26",
                    "-gravity", "NorthEast",
                    "-annotate", "+10+10", preview_path.stem,
                    str(preview_path),
                ],
                "annotate cull preview",
                check=False,
            )
            logging.info("Cull preview: %s", preview_path.name)


def _select_representative(stack_dir: Path, rows: list) -> Optional[Path]:
    """Priority: JPG@EV0 > any JPG > any@EV0 > middle file."""
    files = sorted(stack_dir.iterdir())
    if not files:
        return None

    # Build EV lookup from rows
    ev_by_name: dict = {}
    for row in rows:
        try:
            ev_by_name[row.get("FileName", "")] = float(
                row.get("ExposureCompensation", "0") or "0"
            )
        except ValueError:
            ev_by_name[row.get("FileName", "")] = 0.0

    jpgs = [f for f in files if f.suffix.lower() == ".jpg"]
    jpg_ev0 = [f for f in jpgs if abs(ev_by_name.get(f.name, 0.0)) < 0.01]
    if jpg_ev0:
        return jpg_ev0[0]
    if jpgs:
        return jpgs[0]
    ev0 = [f for f in files if abs(ev_by_name.get(f.name, 0.0)) < 0.01]
    if ev0:
        return ev0[0]
    return files[len(files) // 2]


# ---------------------------------------------------------------------------
# Step 4
# ---------------------------------------------------------------------------


def cmd_stacks_prune(source: Path) -> None:
    """Remove stack dirs that have no surviving cull preview — see README.md § Step 4."""
    cull_dir = source / "cull"
    stack_dirs = sorted(d for d in source.iterdir() if d.is_dir() and d.name.endswith("-stack"))

    for stack_dir in stack_dirs:
        stack_name = stack_dir.name
        if not cull_dir.exists():
            logging.info("No cull/ dir; pruning %s", stack_name)
            shutil.rmtree(stack_dir, ignore_errors=True)
            continue
        previews = list(cull_dir.glob(f"{stack_name}_count*.jpg"))
        if not previews:
            logging.info("Pruning stack with no preview: %s", stack_name)
            shutil.rmtree(stack_dir, ignore_errors=True)

    logging.info("Prune complete")


# ---------------------------------------------------------------------------
# Step 5
# ---------------------------------------------------------------------------


def cmd_stacks_process(
    stacks: List[str],
    source: Path,
    variants_arg: str = "some",
    fast: bool = False,
    quality: int = 80,
    redo: bool = False,
) -> None:
    """Run variant discovery for each stack and write ppsp_generate.csv — see README.md § Step 5."""
    enfuse_ids, tmo_ids = expand_variants(variants_arg)
    z_tier = "z13" if fast else "z25"

    if stacks:
        stack_dirs = [source / s if not Path(s).is_absolute() else Path(s) for s in stacks]
    else:
        stack_dirs = sorted(d for d in source.iterdir() if d.is_dir() and d.name.endswith("-stack"))

    if not stack_dirs:
        logging.warning("No stack directories found")
        return

    csv_path = source / _PHOTOS_CSV
    rows_all = read_photos_csv(csv_path) if csv_path.exists() else []
    rows_by_stack: dict = {}
    for row in rows_all:
        sn = row.get("StackName", "")
        rows_by_stack.setdefault(sn, []).append(row)

    all_generated: List[str] = []

    for stack_dir in stack_dirs:
        if not stack_dir.is_dir():
            logging.warning("Stack dir not found: %s", stack_dir)
            continue
        stack_name = stack_dir.name
        stack_rows = rows_by_stack.get(stack_name, [])
        source_photos = photos_from_csv_rows(stack_rows, stack_dir)
        if not source_photos:
            # Fall back to discovering files in the dir
            from .stacking import photos_from_csv_rows as _pfr
            import re as _re
            source_photos = []
            for f in sorted(stack_dir.iterdir()):
                if f.suffix.lower() in (".arw", ".jpg", ".tif", ".tiff"):
                    source_photos.append(
                        _make_minimal_photo(f)
                    )

        stack_type = detect_stack_type(source_photos)

        generated = process_stack(
            stack_dir=stack_dir,
            stack_name=stack_name,
            stack_type=stack_type,
            enfuse_ids=enfuse_ids,
            tmo_ids=tmo_ids,
            z_tier=z_tier,
            quality=quality,
            source_photos=source_photos,
            redo=redo,
        )
        all_generated.extend(generated)
        logging.info("Stack %s: %d variants generated", stack_name, len(generated))

    # Write ppsp_generate.csv (z100 versions)
    gen_csv_path = source / _GENERATE_CSV
    _write_generate_csv(gen_csv_path, all_generated, redo)
    logging.info(
        "Variant discovery complete. %d total variants. See %s",
        len(all_generated), gen_csv_path,
    )


def _make_minimal_photo(path: Path):
    """Create a Photo stub from a path for stacks without CSV rows."""
    from datetime import datetime
    from .models import Photo
    return Photo(
        path=path,
        filename=path.name,
        source_file=path.name,
        timestamp=datetime.min,
        model="",
        lens="",
        exposure_comp=0.0,
        focal_length=0.0,
        fnumber=0.0,
        white_balance="",
        ext=path.suffix.lower(),
    )


def _write_generate_csv(csv_path: Path, generated: List[str], redo: bool) -> None:
    """Write ppsp_generate.csv with z100 filenames and Generate='-' — see README.md § Step 6."""
    import csv as _csv

    existing: dict = {}
    if csv_path.exists() and not redo:
        with open(csv_path, encoding="utf-8", newline="") as fh:
            for row in _csv.DictReader(fh, delimiter="\t"):
                existing[row.get("Filename", "")] = row.get("Generate", "-")

    rows_out = dict(existing)
    for name in generated:
        z100_name = _to_z100(name)
        rows_out.setdefault(z100_name, "-")

    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=["Filename", "Generate"], delimiter="\t")
        writer.writeheader()
        for filename, gen in sorted(rows_out.items()):
            writer.writerow({"Filename": filename, "Generate": gen})


def _to_z100(filename: str) -> str:
    """Replace z-tier prefix with z100 in a variant filename."""
    import re
    return re.sub(r"-z(100|25|13)-", "-z100-", filename, count=1)


# ---------------------------------------------------------------------------
# Step 7
# ---------------------------------------------------------------------------


def cmd_generate(
    targets: List[str],
    source: Path,
    quality: int = 95,
    redo: bool = False,
) -> None:
    """Generate full-quality variants from chain filenames, CSV, or TXT — see README.md § Step 7."""
    filenames = _resolve_generate_targets(targets, source)
    if not filenames:
        logging.warning("No generate targets found")
        return

    raw_converter = get_raw_converter()
    tmo_ids = list(TMO_VARIANTS.keys())
    out_full = source / "out_full"
    out_web = source / "out_web"

    for filename in filenames:
        spec = parse_chain(filename, tmo_ids=tmo_ids)
        if spec is None:
            logging.warning("Cannot parse chain from %s, skipping", filename)
            continue
        _generate_one(filename, spec, source, raw_converter, quality, out_full, out_web, redo)

    logging.info("Generate complete")


def _resolve_generate_targets(targets: List[str], source: Path) -> List[str]:
    """Resolve targets to a flat list of filenames."""
    import csv as _csv

    if len(targets) == 1:
        t = targets[0]
        p = Path(t)
        if not p.is_absolute():
            p = source / t
        if p.suffix.lower() == ".csv" and p.exists():
            with open(p, encoding="utf-8", newline="") as fh:
                return [
                    row["Filename"]
                    for row in _csv.DictReader(fh, delimiter="\t")
                    if row.get("Generate", "").strip().lower() == "x"
                ]
        if p.suffix.lower() == ".txt" and p.exists():
            return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return list(targets)


def _generate_one(
    filename: str,
    spec: ChainSpec,
    source: Path,
    raw_converter: Optional[str],
    quality: int,
    out_full: Path,
    out_web: Path,
    redo: bool,
) -> None:
    """Execute chain steps for a single target filename — see DESIGN.md § --generate chain execution."""
    # Derive stack dir from filename convention
    # Filename: YYYYMMDDHHMMSS-CCCxxx-NNNN-chain.jpg
    # Stack dir: YYYYMMDDHHMMSS-CCCxxx-NNNN-stack/
    parts = filename.split("-")
    if len(parts) < 4:
        logging.warning("Cannot derive stack dir from %s", filename)
        return
    stack_base = "-".join(parts[:3]) + "-stack"
    stack_dir = source / stack_base
    if not stack_dir.is_dir():
        logging.warning("Stack dir not found: %s", stack_dir)
        return

    # Find source ARWs in stack dir
    arws = sorted(stack_dir.glob("*.arw")) + sorted(stack_dir.glob("*.ARW"))
    if not arws:
        logging.warning("No ARW files in %s", stack_dir)
        return

    if raw_converter is None:
        logging.error("No raw converter available for %s", filename)
        return

    # Step 1: convert
    tiff_files: List[Path] = []
    for arw in arws:
        out_tif = stack_dir / f"{arw.stem}_{spec.z_tier}.tif"
        ok = convert_raw_to_tiff(arw, out_tif, spec.z_tier, raw_converter, redo=redo)
        if ok:
            tiff_files.append(out_tif)

    if not tiff_files:
        logging.error("No TIFFs produced for %s", filename)
        return

    # Step 2: align
    align_prefix = str(stack_dir / f"aligned_{spec.z_tier}_")
    is_hdr = spec.tmo_id is not None
    aligned = align_stack(tiff_files, align_prefix, is_hdr=is_hdr, redo=redo)
    if not aligned:
        logging.error("Alignment failed for %s", filename)
        return

    # Step 3: enfuse
    enfuse_tif = stack_dir / f"temp_{spec.z_tier}_{spec.enfuse_id}.tif"
    ok = run_enfuse(aligned, enfuse_tif, spec.enfuse_id, redo=redo)
    if not ok:
        logging.error("Enfuse failed for %s", filename)
        return

    # Step 4: TMO (optional)
    if spec.tmo_id:
        tmo_jpg = stack_dir / f"temp_{spec.z_tier}_{spec.enfuse_id}_{spec.tmo_id}.jpg"
        ok = run_tmo(enfuse_tif, tmo_jpg, spec.tmo_id, quality, redo=redo)
        if not ok:
            logging.error("TMO failed for %s", filename)
            return
        grading_src = tmo_jpg
    else:
        grading_src = enfuse_tif

    # Step 5: grading
    out_name = Path(filename).name
    final_jpg = stack_dir / out_name
    ok = apply_grading(grading_src, final_jpg, spec.grading_id, quality, redo=redo)
    if not ok:
        logging.error("Grading failed for %s", filename)
        return

    # Copy EXIF from middle ARW
    mid_arw = arws[len(arws) // 2]
    from .processing import _copy_exif
    _copy_exif(mid_arw, final_jpg)

    # Step 6: export
    export_variants([final_jpg], source, redo=redo)
    logging.info("Generated: %s", filename)


# ---------------------------------------------------------------------------
# Enhance ARWs
# ---------------------------------------------------------------------------


def cmd_arws_enhance(
    files: List[Path],
    source: Path,
    quality: int = 90,
    redo: bool = False,
) -> None:
    """Convert ARW files to enhanced JPGs — see README.md § arws-enhance."""
    if not files:
        files = list(source.glob("**/*.arw")) + list(source.glob("**/*.ARW"))
    if not files:
        logging.warning("No ARW files found")
        return

    raw_converter = get_raw_converter()
    if raw_converter is None:
        logging.error("No raw converter available")
        return

    for arw in files:
        out_jpg = arw.with_name(f"{arw.stem}_enhanced.jpg")
        ok = create_jpg_from_arw(arw, out_jpg, quality, raw_converter, redo=redo)
        if ok:
            logging.info("Enhanced: %s", out_jpg.name)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cmd_cleanup(source: Path) -> None:
    """Remove intermediate TIFFs from stack directories — see README.md § cleanup."""
    removed = 0
    for stack_dir in source.iterdir():
        if not stack_dir.is_dir() or not stack_dir.name.endswith("-stack"):
            continue
        for pattern in ("aligned_*.tif", "temp_*.tif", "aligned_*.tiff", "temp_*.tiff"):
            for f in stack_dir.glob(pattern):
                f.unlink(missing_ok=True)
                removed += 1
    logging.info("Cleanup removed %d intermediate TIFFs", removed)


# ---------------------------------------------------------------------------
# Full workflow
# ---------------------------------------------------------------------------


def run_full_workflow(
    source: Path,
    gap: float = 30.0,
    quality: int = 80,
    batch: bool = False,
    verbose: bool = False,
    redo: bool = False,
    default_model: str = "",
    default_lens: str = "",
    variants_arg: str = "some",
    fast: bool = False,
) -> None:
    """Run all steps in sequence, prompting between each unless --batch — see DESIGN.md § Workflow."""

    def _prompt(msg: str) -> bool:
        if batch:
            return True
        ans = input(f"{msg} [Y/n]: ").strip().lower()
        return ans != "n"

    logging.info("=== Full workflow starting ===")

    if _prompt("Step 1: Rename and catalogue"):
        cmd_rename([], source, default_model=default_model, default_lens=default_lens, redo=redo)

    if _prompt("Step 2: Organize stacks"):
        cmd_stacks_organize([], source, gap=gap, redo=redo)

    if _prompt("Step 3: Generate culling previews"):
        cmd_stacks_cull(source, quality=quality, redo=redo)

    if not batch:
        logging.info("Review cull/ with your image viewer, then delete unwanted previews.")
        input("Press Enter when culling is done...")

    if _prompt("Step 4: Prune rejected stacks"):
        cmd_stacks_prune(source)

    if _prompt("Step 5: Variant discovery"):
        cmd_stacks_process([], source, variants_arg=variants_arg, fast=fast, quality=quality, redo=redo)

    if not batch:
        logging.info("Edit ppsp_generate.csv — mark variants with 'x' in the Generate column.")
        input("Press Enter when selection is done...")

    if _prompt("Step 7: Generate selected variants"):
        gen_csv = source / _GENERATE_CSV
        if gen_csv.exists():
            cmd_generate([str(gen_csv)], source, quality=95, redo=redo)

    logging.info("=== Full workflow complete ===")
