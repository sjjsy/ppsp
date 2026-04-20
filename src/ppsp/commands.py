"""One cmd_* function per CLI step — see DESIGN.md § CLI-to-function mapping."""

from __future__ import annotations

import logging
import os
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
from .variants import GRADING_PRESETS, TMO_VARIANTS, expand_variants, parse_full_chain_spec, parse_variant_chain

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
    tokens = [t.strip() for t in variants_arg.split(",") if t.strip()]
    chain_specs: List[ChainSpec] = []
    grading_ids: List[str] = []
    if any("-" in t for t in tokens):
        # Mode 3: exact chain specs
        for t in tokens:
            spec = parse_variant_chain(t)
            if spec is not None:
                chain_specs.append(spec)
            else:
                logging.warning("Unknown chain spec '%s' in --variants, skipping", t)
        enfuse_ids: List[str] = []
        tmo_ids: List[str] = []
    else:
        # Mode 1 (preset) or Mode 2 (bare IDs)
        enfuse_ids, tmo_ids, grading_ids = expand_variants(variants_arg)

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
            grading_ids=grading_ids if grading_ids else None,
            chain_specs=chain_specs,
            redo=redo,
        )
        all_generated.extend(generated)
        logging.info("Stack %s: %d variants generated", stack_name, len(generated))

        # Hard-link variants + collage into source/variants/ for easy culling
        variants_dir = source / "variants"
        variants_dir.mkdir(exist_ok=True)
        output_dir = stack_dir / z_tier
        collage_name = f"{stack_name}-collage.jpg"
        for name in list(generated) + [collage_name]:
            src_path = output_dir / name
            if not src_path.exists():
                continue
            dst_path = variants_dir / name
            if dst_path.exists():
                continue
            try:
                os.link(src_path, dst_path)
            except OSError:
                shutil.copy2(src_path, dst_path)

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


def _looks_like_chain_spec(s: str) -> bool:
    """Return True if s is a z-tier chain spec (e.g. z25-sel4-ma06-dvi1), not a file path."""
    import re
    return bool(re.match(r"^z(100|25|13)-", s)) and "/" not in s and "\\" not in s


def _expand_chain_spec_to_all_stacks(spec: "ChainSpec", source: Path) -> List[str]:
    """Return one canonical filename per stack under source for the given chain spec."""
    stack_dirs = sorted(d for d in source.iterdir() if d.is_dir() and d.name.endswith("-stack"))
    if not stack_dirs:
        logging.warning("No stack directories found under %s", source)
    filenames = []
    for stack_dir in stack_dirs:
        base = stack_dir.name[: -len("-stack")]
        if spec.tmo_id:
            name = f"{base}-{spec.z_tier}-{spec.enfuse_id}-{spec.tmo_id}-{spec.grading_id}.jpg"
        else:
            name = f"{base}-{spec.z_tier}-{spec.enfuse_id}-{spec.grading_id}.jpg"
        filenames.append(name)
    return filenames


def _to_ztier(filename: str, z_tier: str) -> str:
    """Replace the z-tier token in a variant filename with the requested tier."""
    import re
    return re.sub(r"-z(100|25|13)-", f"-{z_tier}-", filename, count=1)


def _has_ztier(filename: str) -> bool:
    """Return True if filename contains a z-tier token (-z100-, -z25-, or -z13-)."""
    import re
    return bool(re.search(r"-z(100|25|13)-", filename))


def _to_z100(filename: str) -> str:
    return _to_ztier(filename, "z100")


# ---------------------------------------------------------------------------
# Step 7
# ---------------------------------------------------------------------------


def cmd_generate(
    targets: List[str],
    source: Path,
    quality: int = 95,
    redo: bool = False,
    half: bool = False,
) -> None:
    """Generate variants from chain filenames, CSV, or TXT — see README.md § Step 7.

    With half=True, generates at z25 (dcraw -h) instead of z100 (full resolution).
    All z25 intermediates from the discovery phase are reused automatically.
    """
    z_tier = "z25" if half else "z100"
    filenames = _resolve_generate_targets(targets, source, z_tier=z_tier)
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


def _resolve_generate_targets(
    targets: List[str],
    source: Path,
    z_tier: str = "z100",
) -> List[str]:
    """Resolve targets to a flat list of filenames to generate.

    Accepted forms:
      - z-tier chain spec (e.g. 'z25-sel4-ma06-dvi1'): expand to all stacks under source.
      - A directory path: scan for *.jpg with a z-tier token, convert each to z_tier.
      - A .csv path: rows where Generate == 'x'; filenames read as-is (z-tier from filename).
      - A .txt path: one filename per line, read as-is.
      - Direct filenames on the command line.
    Multiple chain specs may be passed together; they are each expanded across all stacks.
    """
    import csv as _csv

    # If every target is a chain spec, expand them all to all stacks.
    # Also handle the common single-chain-spec case here before file checks.
    if targets and all(_looks_like_chain_spec(t) for t in targets):
        filenames = []
        for t in targets:
            spec = parse_full_chain_spec(t)
            if spec is not None:
                filenames.extend(_expand_chain_spec_to_all_stacks(spec, source))
            else:
                logging.warning("Cannot parse chain spec '%s', skipping", t)
        return filenames

    # Single-target special cases: directory, CSV, TXT
    if len(targets) == 1:
        t = targets[0]
        p = Path(t)
        if not p.is_absolute():
            p = source / t

        if p.is_dir():
            filenames = []
            for f in sorted(p.glob("*.jpg")):
                if _has_ztier(f.name):
                    filenames.append(_to_ztier(f.name, z_tier))
            if not filenames:
                logging.warning("No variant JPGs found in %s", p)
            return filenames

        if p.suffix.lower() == ".csv" and p.exists():
            with open(p, encoding="utf-8", newline="") as fh:
                return [
                    row["Filename"]
                    for row in _csv.DictReader(fh, delimiter="\t")
                    if row.get("Generate", "").strip().lower() == "x"
                ]

        if p.suffix.lower() == ".txt" and p.exists():
            return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # Multiple targets: process each — chain specs expand, everything else is a filename.
    filenames = []
    for t in targets:
        if _looks_like_chain_spec(t):
            spec = parse_full_chain_spec(t)
            if spec is not None:
                filenames.extend(_expand_chain_spec_to_all_stacks(spec, source))
            else:
                logging.warning("Cannot parse chain spec '%s', skipping", t)
        else:
            filenames.append(t)
    return filenames


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

    # Combined outputs live in the z-tier subfolder (mirrors process_stack layout)
    out_base = "-".join(parts[:3])  # e.g. "20260411152701-m4aens-2324"
    z_dir = stack_dir / spec.z_tier
    z_dir.mkdir(exist_ok=True)

    # Step 1: convert — per-frame TIFs stay in stack root alongside the ARWs
    tiff_files: List[Path] = []
    for arw in arws:
        out_tif = stack_dir / f"{arw.stem}-{spec.z_tier}.tif"
        ok = convert_raw_to_tiff(arw, out_tif, spec.z_tier, raw_converter, redo=redo)
        if ok:
            tiff_files.append(out_tif)

    if not tiff_files:
        logging.error("No TIFFs produced for %s", filename)
        return

    # Step 2: align — skipped for single-frame stacks; aligned TIFs go into z_dir
    if len(tiff_files) < 2:
        logging.info("Single-frame stack — skipping alignment for %s", filename)
        aligned = tiff_files
    else:
        align_prefix = str(z_dir / f"{out_base}-{spec.z_tier}-aligned")
        is_hdr = spec.tmo_id is not None
        aligned = align_stack(tiff_files, align_prefix, is_hdr=is_hdr, redo=redo)
        if not aligned:
            logging.error("Alignment failed for %s", filename)
            return

    # Step 3: enfuse — temp TIF goes into z_dir
    enfuse_tif = z_dir / f"{out_base}-{spec.z_tier}-{spec.enfuse_id}.tif"
    ok = run_enfuse(aligned, enfuse_tif, spec.enfuse_id, redo=redo)
    if not ok:
        logging.error("Enfuse failed for %s", filename)
        return

    # Step 4: TMO (optional) — temp JPG goes into z_dir
    if spec.tmo_id:
        tmo_jpg = z_dir / f"{out_base}-{spec.z_tier}-{spec.enfuse_id}-{spec.tmo_id}.jpg"
        ok = run_tmo(enfuse_tif, tmo_jpg, spec.tmo_id, quality, redo=redo)
        if not ok:
            logging.error("TMO failed for %s", filename)
            return
        grading_src = tmo_jpg
    else:
        grading_src = enfuse_tif

    # Step 5: grading — staged final JPG also goes into z_dir
    out_name = Path(filename).name
    final_jpg = z_dir / out_name
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
    """Remove intermediate files from z-tier subfolders in stack directories — see README.md § cleanup."""
    from .variants import GRADING_PRESETS
    grading_ids = set(GRADING_PRESETS.keys())
    removed = 0
    for stack_dir in source.iterdir():
        if not stack_dir.is_dir() or not stack_dir.name.endswith("-stack"):
            continue
        for z_dir in stack_dir.iterdir():
            if not z_dir.is_dir() or not z_dir.name.startswith("z"):
                continue
            for f in z_dir.iterdir():
                if f.suffix.lower() in (".tif", ".tiff"):
                    # All TIFs in z-tier subdirs are intermediates (aligned + enfuse temps)
                    f.unlink(missing_ok=True)
                    removed += 1
                elif f.suffix.lower() == ".jpg":
                    # Keep finals (last chain component is a grading id) and collages
                    last_part = f.stem.rsplit("-", 1)[-1]
                    if last_part not in grading_ids and last_part != "collage":
                        f.unlink(missing_ok=True)
                        removed += 1
    logging.info("Cleanup removed %d intermediate files", removed)


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
    half: bool = False,
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

    selection_method = "folder"
    if not batch:
        variants_dir = source / "variants"
        logging.info("")
        logging.info("Step 6 — Variant selection. Choose a method:")
        logging.info("  1. Folder-based (default): delete unwanted files from %s/", variants_dir)
        logging.info("     then run --generate variants/ (hard-linked to stack z-tier subfolders)")
        logging.info("  2. CSV-based: edit ppsp_generate.csv, mark keepers with 'x' in Generate column")
        ans = input("Method [1/2, default=1]: ").strip()
        selection_method = "csv" if ans == "2" else "folder"
        input("Press Enter when selection is done...")

    if _prompt("Step 7: Generate selected variants"):
        if selection_method == "csv":
            gen_csv = source / _GENERATE_CSV
            if gen_csv.exists():
                cmd_generate([str(gen_csv)], source, quality=95, redo=redo, half=half)
            else:
                logging.warning("ppsp_generate.csv not found; skipping generate step")
        else:
            variants_dir = source / "variants"
            if variants_dir.exists():
                cmd_generate([str(variants_dir)], source, quality=95, redo=redo, half=half)
            else:
                logging.warning("variants/ folder not found; skipping generate step")

    logging.info("=== Full workflow complete ===")
