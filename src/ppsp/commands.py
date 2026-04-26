"""One cmd_* function per CLI step — see design.md § CLI-to-function mapping."""

from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable, List, Optional, Set, TypeVar

from .export import export_variants as _export_variants
from .models import ChainSpec, StackType, parse_chain
from .naming import (
    STACKS_CSV,
    _RAW_EXTS,
    build_stacks_csv_rows,
    find_stack_dirs,
    is_stack_dir,
    load_stacks_csv,
    rename_stack,
    save_stacks_csv,
    stack_dir_to_filename_base,
    title_to_shorthand,
    write_metadata_to_stack,
    write_sidecar,
)
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
from .variants import (
    GRADING_PRESETS,
    TMO_VARIANTS,
    Z_TIERS,
    expand_chain_pattern,
    expand_variant_chain_pattern,
    expand_variants,
    parse_full_chain_spec,
    parse_variant_chain,
)

_PHOTOS_CSV = "ppsp_photos.csv"
_GENERATE_CSV = "ppsp_generate.csv"

_F = TypeVar("_F", bound=Callable)


def _timed_cmd(fn: _F) -> _F:
    """Log elapsed wall time after a cmd_* call when execution exceeds 4 seconds."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        if elapsed > 4:
            logging.info("%.1fs — %s complete", elapsed, fn.__name__)
        return result
    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# RENAME
# ---------------------------------------------------------------------------


@_timed_cmd
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
# ORGANIZE
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_organize(
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
# CULL
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_cull(source: Path, quality: int = 80, redo: bool = False) -> None:
    """Generate labeled culling previews in cull/ — see README.md § Step 3."""
    cull_dir = source / "cull"
    cull_dir.mkdir(exist_ok=True)

    stack_dirs = find_stack_dirs(source)
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
            parts = stack_name.split("-")
            nnnn = parts[2] if len(parts) >= 3 else stack_name
            run_command(
                [
                    "mogrify",
                    "-font", "Liberation-Sans-Bold",
                    "-fill", "white",
                    "-undercolor", "#00000099",
                    "-pointsize", "36",
                    "-gravity", "South",
                    "-annotate", "+0+36",
                    nnnn,
                    "-font", "Liberation-Sans",
                    "-pointsize", "22",
                    "-gravity", "South",
                    "-annotate", "+0+8",
                    f"×{count}",
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
# PRUNE
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_prune(source: Path) -> None:
    """Remove stack dirs that have no surviving cull preview — see README.md § Step 4."""
    cull_dir = source / "cull"
    stack_dirs = find_stack_dirs(source)

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
# NAME
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_name(
    source: Path,
    stacks_specs: Optional[List[str]] = None,
    title: Optional[str] = None,
    csv_path: Optional[Path] = None,
    redo: bool = False,
    batch: bool = False,
) -> None:
    """Name stacks interactively, from CSV, or inline — see README.md § Naming."""
    # Always sync ppsp_stacks.csv first.
    existing = load_stacks_csv(source)
    rows = build_stacks_csv_rows(source, existing)

    stacks_filter = _resolve_stack_specs(stacks_specs or [], source) if stacks_specs else None

    if csv_path is not None:
        # CSV mode: apply titles from the supplied stacks CSV.
        _name_from_csv(source, csv_path, rows, redo=redo)

    elif title is not None:
        # Inline mode: apply a single title to the one selected stack.
        targets = [
            d for d in find_stack_dirs(source)
            if stacks_filter is None or d.name in stacks_filter
        ]
        if len(targets) != 1:
            logging.error(
                "Inline title requires exactly one stack; got %d matching stacks", len(targets)
            )
        else:
            _name_apply_one(targets[0], title, source, rows, redo=redo)
            rows = build_stacks_csv_rows(source, rows)

    elif not batch:
        # Interactive mode: offer one-by-one or CSV-edit.
        print("\nHow would you like to name stacks?")
        print("  [a] Name one-by-one in terminal (default)")
        print("  [b] Open ppsp_stacks.csv for editing")
        try:
            choice = input("Choice [a/b]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = ""

        if choice == "b":
            # Write CSV, open in system editor, re-ingest on return.
            save_stacks_csv(source, rows)
            edit_csv = source / STACKS_CSV
            try:
                import subprocess as _sp
                _sp.Popen(["xdg-open", str(edit_csv)])
            except OSError as exc:
                logging.warning("Could not open CSV: %s", exc)
            input(f"\nEditing {edit_csv.name} — press Enter when done...")
            _name_from_csv(source, edit_csv, rows, redo=redo)
        else:
            # One-by-one prompting.
            targets = [
                d for d in find_stack_dirs(source)
                if stacks_filter is None or d.name in stacks_filter
            ]
            rows_by_folder = {r["StackFolder"]: r for r in rows}
            for stack_dir in targets:
                row = rows_by_folder.get(stack_dir.name, {})
                existing_title = row.get("Title", "")
                prefix = f"\nStack: {stack_dir.name}  ({row.get('RawPhotoCount', '?')} RAW files)"
                if existing_title:
                    prefix += f"\n  Current: {existing_title}"
                try:
                    answer = input(prefix + "\n  Title (Enter to keep): ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if answer:
                    _name_apply_one(stack_dir, answer, source, rows, redo=redo)
                    rows = build_stacks_csv_rows(source, rows)
                    rows_by_folder = {r["StackFolder"]: r for r in rows}

    save_stacks_csv(source, rows)
    logging.info("ppsp_stacks.csv updated: %s", source / STACKS_CSV)


def _name_apply_one(
    stack_dir: Path,
    title: str,
    source: Path,
    rows: List[dict],
    redo: bool = False,
    tags: str = "",
    rating: str = "",
) -> None:
    """Apply title/tags/rating to one stack: rename folder+files, write metadata+sidecar, update rows."""
    old_name = stack_dir.name
    new_dir = rename_stack(stack_dir, title, source)
    if new_dir is None:
        return
    write_metadata_to_stack(new_dir, title, tags=tags, rating=rating)
    write_sidecar(new_dir, title, tags=tags, rating=rating)
    shorthand = title_to_shorthand(title)
    for row in rows:
        if row["StackFolder"] == old_name or row["StackFolder"] == new_dir.name:
            row["StackFolder"] = new_dir.name
            row["Title"] = title
            row["Shorthand"] = shorthand
            if tags:
                row["Tags"] = tags
            if rating:
                row["Rating"] = rating
            break
    else:
        raw_count = sum(1 for f in new_dir.iterdir() if f.is_file() and f.suffix.lower() in _RAW_EXTS)
        rows.append({
            "StackFolder": new_dir.name,
            "RawPhotoCount": str(raw_count),
            "Title": title,
            "Shorthand": shorthand,
            "Tags": tags,
            "Rating": rating,
            "GenerateSpecs": "",
        })


def _name_from_csv(
    source: Path,
    csv_path: Path,
    rows: List[dict],
    redo: bool = False,
) -> None:
    """Apply titles/tags/ratings from a stacks CSV to rows with a non-empty Title field."""
    import csv as _csv

    if not csv_path.exists():
        logging.error("CSV not found: %s", csv_path)
        return

    with open(csv_path, encoding="utf-8", newline="") as fh:
        csv_rows = list(_csv.DictReader(fh, delimiter="\t"))

    rows_by_folder = {r["StackFolder"]: r for r in rows}
    for csv_row in csv_rows:
        folder = csv_row.get("StackFolder", "").strip()
        title = csv_row.get("Title", "").strip()
        if not title or not folder:
            continue
        stack_dir = source / folder
        if not stack_dir.exists():
            logging.warning("Stack dir not found: %s", folder)
            continue
        tags = csv_row.get("Tags", "").strip()
        rating = csv_row.get("Rating", "").strip()
        prev = rows_by_folder.get(folder, {})
        if (prev.get("Title") == title and prev.get("Tags") == tags
                and prev.get("Rating") == rating and not redo):
            continue
        _name_apply_one(stack_dir, title, source, rows, redo=redo, tags=tags, rating=rating)
        # Refresh index after rename may have changed folder name
        rows_by_folder = {r["StackFolder"]: r for r in rows}


# ---------------------------------------------------------------------------
# DISCOVER
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_discover(
    source: Path,
    variants_arg: str = "some",
    z_tier: str = "z25",
    quality: int = 80,
    redo: bool = False,
    stacks_specs: Optional[List[str]] = None,
    batch: bool = False,
) -> None:
    """Run variant discovery for each stack and write ppsp_generate.csv — see README.md § --variants."""
    tokens = [t.strip() for t in variants_arg.split(",") if t.strip()]
    chain_specs: List[ChainSpec] = []
    grading_ids: List[str] = []
    ct_ids: List[str] = []
    if any("-" in t or _is_chain_pattern(t) for t in tokens):
        # Mode 3: exact chain specs or regex patterns (no z-tier; z_tier is applied at processing time)
        for t in tokens:
            if _is_chain_pattern(t):
                for chain_str in expand_variant_chain_pattern(t):
                    spec = parse_variant_chain(chain_str)
                    if spec is not None:
                        chain_specs.append(spec)
            else:
                spec = parse_variant_chain(t)
                if spec is not None:
                    chain_specs.append(spec)
                else:
                    msg = f"Unknown chain spec '{t}' in --variants"
                    if batch:
                        logging.warning("%s, skipping", msg)
                    else:
                        raise ValueError(msg)
        enfuse_ids: List[str] = []
        tmo_ids: List[str] = []
    else:
        # Mode 1 (preset) or Mode 2 (bare IDs)
        enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants(variants_arg)

    stacks_filter = _resolve_stack_specs(stacks_specs or [], source)
    if stacks_filter is not None:
        stack_dirs = sorted(source / name for name in sorted(stacks_filter) if (source / name).is_dir())
    else:
        stack_dirs = find_stack_dirs(source)

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
            ct_ids=ct_ids if ct_ids else None,
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
    """Write ppsp_generate.csv with z100 filenames and empty Generate column — see README.md § Step 7."""
    import csv as _csv

    existing: dict = {}
    if csv_path.exists() and not redo:
        with open(csv_path, encoding="utf-8", newline="") as fh:
            for row in _csv.DictReader(fh, delimiter="\t"):
                existing[row.get("Filename", "")] = row.get("Generate", "")

    rows_out = dict(existing)
    for name in generated:
        z100_name = _to_z100(name)
        rows_out.setdefault(z100_name, "")

    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=["Filename", "Generate"], delimiter="\t")
        writer.writeheader()
        for filename, gen in sorted(rows_out.items()):
            writer.writerow({"Filename": filename, "Generate": gen})


def _derive_stack_from_filename(filename: str) -> Optional[str]:
    """Derive stack dir name from a variant filename.

    Handles both old-style (NNNN-z25-...) → NNNN-stack
    and named-stack (NNNN-shorthand-z25-...) → NNNN-shorthand.
    """
    parts = Path(filename).stem.split("-")
    if len(parts) < 4:
        return None
    if parts[3] in Z_TIERS:
        return "-".join(parts[:3]) + "-stack"
    return "-".join(parts[:4])


def _resolve_stack_specs(specs: List[str], source: Path) -> Optional[Set[str]]:
    """Resolve --stacks specs to a set of stack dir names; returns None when specs is empty.

    Accepted per-token forms:
      - Full stack name ending in '-stack'
      - 4-digit frame number (NNNN) or range NNNN-NNNN
      - File path to a variant JPG (stack name derived from the filename)
      - Path to a .csv file (Filename column used to derive stack names)
      - Path to a .txt file (one filename per line used to derive stack names)
    """
    import csv as _csv
    import re as _re
    if not specs:
        return None
    result: Set[str] = set()
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue

        p = Path(spec)
        if not p.is_absolute():
            p_resolved = source / spec
        else:
            p_resolved = p

        # CSV file: derive stack names from Filename column
        if p_resolved.suffix.lower() == ".csv" and p_resolved.exists():
            with open(p_resolved, encoding="utf-8", newline="") as fh:
                for row in _csv.DictReader(fh, delimiter="\t"):
                    fname = row.get("Filename", "").strip()
                    sn = _derive_stack_from_filename(fname)
                    if sn:
                        result.add(sn)
            continue

        # TXT file: derive stack names from filenames listed one per line
        if p_resolved.suffix.lower() == ".txt" and p_resolved.exists():
            for line in p_resolved.read_text(encoding="utf-8").splitlines():
                fname = line.strip()
                if fname:
                    sn = _derive_stack_from_filename(fname)
                    if sn:
                        result.add(sn)
            continue

        # Existing file (e.g. JPG variant): derive stack name from filename
        if p_resolved.exists() and p_resolved.is_file():
            sn = _derive_stack_from_filename(p_resolved.name)
            if sn:
                result.add(sn)
            continue

        # Non-existent path that looks like a variant filename (shell-expanded glob residue)
        if p.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff"):
            sn = _derive_stack_from_filename(p.name)
            if sn:
                result.add(sn)
            continue

        # Full stack dir name (old-style -stack or named shorthand)
        if (source / spec).is_dir() and is_stack_dir(source / spec):
            result.add(spec)
        # NNNN-NNNN range
        elif _re.match(r"^\d{1,4}-\d{1,4}$", spec):
            lo, hi = int(spec.split("-")[0]), int(spec.split("-")[1])
            for d in find_stack_dirs(source):
                parts = d.name.split("-")
                if len(parts) >= 3 and parts[2].isdigit():
                    n = int(parts[2])
                    if lo <= n <= hi:
                        result.add(d.name)
        # Single frame number
        elif _re.match(r"^\d+$", spec):
            nnnn = spec.zfill(4)
            for d in find_stack_dirs(source):
                parts = d.name.split("-")
                if len(parts) >= 3 and parts[2] == nnnn:
                    result.add(d.name)
        else:
            logging.warning("Cannot parse stack spec '%s', skipping", spec)
    return result


def _filename_to_stack_name(filename: str) -> Optional[str]:
    """Derive the stack directory name from a variant filename.

    Handles both old-style filenames (NNNN-z25-...) → NNNN-stack
    and named-stack filenames (NNNN-shorthand-z25-...) → NNNN-shorthand.
    """
    parts = Path(filename).stem.split("-")
    if len(parts) < 4:
        return None
    if parts[3] in Z_TIERS:
        # Old-style: no shorthand
        return "-".join(parts[:3]) + "-stack"
    # Named stack: shorthand is the 4th component
    return "-".join(parts[:4])


def _looks_like_chain_spec(s: str) -> bool:
    """Return True if s is a z-tier chain spec (possibly with regex wildcards), not a file path."""
    if "/" in s or "\\" in s:
        return False
    return bool(re.match(r"^z(100|25|6|2)-", s))


def _is_chain_pattern(s: str) -> bool:
    """Return True if s contains Python regex metacharacters (not a literal chain spec)."""
    return bool(re.search(r"[*.({\[?+|]", s))


def _expand_chain_spec_to_all_stacks(
    spec: "ChainSpec",
    source: Path,
    stacks_filter: Optional[Set[str]] = None,
) -> List[str]:
    """Return one canonical filename per stack under source for the given chain spec."""
    stack_dirs = find_stack_dirs(source)
    if stacks_filter is not None:
        stack_dirs = [d for d in stack_dirs if d.name in stacks_filter]
    if not stack_dirs:
        logging.warning("No stack directories found under %s", source)
    filenames = []
    for stack_dir in stack_dirs:
        base = stack_dir_to_filename_base(stack_dir.name)
        if spec.tmo_id:
            chain = f"{spec.enfuse_id}-{spec.tmo_id}-{spec.grading_id}"
        else:
            chain = f"{spec.enfuse_id}-{spec.grading_id}"
        if spec.ct_id:
            chain += f"-{spec.ct_id}"
        name = f"{base}-{spec.z_tier}-{chain}.jpg"
        filenames.append(name)
    return filenames


def _to_ztier(filename: str, z_tier: str) -> str:
    """Replace the z-tier token in a variant filename with the requested tier."""
    return re.sub(r"-z(100|25|6|2)-", f"-{z_tier}-", filename, count=1)


def _has_ztier(filename: str) -> bool:
    """Return True if filename contains a z-tier token (-z100-, -z25-, -z6-, or -z2-)."""
    return bool(re.search(r"-z(100|25|6|2)-", filename))


def _to_z100(filename: str) -> str:
    return _to_ztier(filename, "z100")


# ---------------------------------------------------------------------------
# GENERATE
# ---------------------------------------------------------------------------


@_timed_cmd
def cmd_generate(
    source: Path,
    variants_arg: str = "variants/",
    z_tier: str = "z100",
    quality: int = 80,
    resolution: Optional[int] = None,
    redo: bool = False,
    stacks_specs: Optional[List[str]] = None,
) -> None:
    """Generate full-quality variants from --variants spec — see README.md § --variants."""
    stacks_filter = _resolve_stack_specs(stacks_specs or [], source)
    filenames = _resolve_variants_for_generate(variants_arg, z_tier, source, stacks_filter)
    if not filenames:
        logging.warning("No generate targets found")
        return

    raw_converter = get_raw_converter()
    tmo_ids = list(TMO_VARIANTS.keys())

    new_count = 0
    skip_count = 0
    for filename in filenames:
        spec = parse_chain(filename, tmo_ids=tmo_ids)
        if spec is None:
            logging.warning("Cannot parse chain from %s, skipping", filename)
            continue
        generated = _generate_one(filename, spec, source, raw_converter, quality, resolution, redo)
        if generated:
            new_count += 1
        else:
            skip_count += 1

    out_desc = f"out-{resolution}/" if resolution else "out-BBBB/"
    if skip_count > 0 and new_count == 0:
        logging.info("All %d requested variants already exist in %s", skip_count, out_desc)
    elif skip_count > 0:
        logging.info("Generated %d new variants; %d already existed", new_count, skip_count)
    else:
        logging.info("Generate complete — %d variants → %s", new_count, out_desc)


def _resolve_stacks_csv_for_generate(
    csv_rows: List[dict],
    z_tier: str,
    source: Path,
    stacks_filter: Optional[Set[str]],
) -> List[str]:
    """Expand ppsp_stacks.csv GenerateSpecs into target filenames for --generate."""
    filenames: List[str] = []
    for row in csv_rows:
        folder = row.get("StackFolder", "").strip()
        specs_raw = row.get("GenerateSpecs", "").strip()
        if not folder or not specs_raw:
            continue
        if stacks_filter is not None and folder not in stacks_filter:
            continue
        stack_dir = source / folder
        if not stack_dir.is_dir():
            logging.warning("Stack dir not found: %s", folder)
            continue
        file_base = stack_dir_to_filename_base(folder)
        for spec_str in [s.strip() for s in specs_raw.split(",") if s.strip()]:
            # Allow spec with or without leading z-tier; normalise to target z_tier.
            normalised = re.sub(r"^z(100|25|6|2)-", "", spec_str)
            full_spec = f"{z_tier}-{normalised}"
            spec = parse_full_chain_spec(full_spec)
            if spec is None:
                logging.warning("Cannot parse generate spec '%s' for %s", spec_str, folder)
                continue
            chain = spec.enfuse_id
            if spec.tmo_id:
                chain += f"-{spec.tmo_id}"
            chain += f"-{spec.grading_id}"
            if spec.ct_id:
                chain += f"-{spec.ct_id}"
            filenames.append(f"{file_base}-{z_tier}-{chain}.jpg")
    return filenames


def _resolve_variants_for_generate(
    variants_arg: str,
    z_tier: str,
    source: Path,
    stacks_filter: Optional[Set[str]],
) -> List[str]:
    """Resolve --variants to a flat list of target filenames for --generate.

    Accepted forms (tried in order):
      - Directory path: scan for *.jpg variant files, rewrite z-tier.
      - .csv path: rows where Generate == 'x', rewrite z-tier.
      - .txt path: one filename per line, rewrite z-tier.
      - Chain spec / regex pattern (with or without leading z-tier): expand to all stacks.
      - Preset level or comma-separated IDs: build cross-product, expand to all stacks.
    Any z-tier embedded in a chain spec string is replaced by z_tier.
    """
    import csv as _csv

    # File-path forms
    p = Path(variants_arg)
    if not p.is_absolute():
        p = source / variants_arg

    _YES_VALUES = frozenset({"x", "+", "y", "yes"})

    if p.is_dir():
        filenames = []
        for f in sorted(p.glob("*.jpg")):
            if _has_ztier(f.name):
                if stacks_filter is None or _filename_to_stack_name(f.name) in stacks_filter:
                    filenames.append(_to_ztier(f.name, z_tier))
        if not filenames:
            logging.warning("No variant JPGs found in %s", p)
        return filenames

    if p.suffix.lower() in (".jpg", ".jpeg") and p.exists():
        if _has_ztier(p.name) and (stacks_filter is None or _filename_to_stack_name(p.name) in stacks_filter):
            return [_to_ztier(p.name, z_tier)]
        return []

    if p.suffix.lower() == ".csv" and p.exists():
        with open(p, encoding="utf-8", newline="") as fh:
            csv_rows = list(_csv.DictReader(fh, delimiter="\t"))

        # Detect format by checking column names.
        if csv_rows and "StackFolder" in csv_rows[0]:
            # ppsp_stacks.csv format: expand per-stack GenerateSpecs.
            return _resolve_stacks_csv_for_generate(csv_rows, z_tier, source, stacks_filter)

        # ppsp_generate.csv format: Filename + Generate columns.
        filenames_from_csv = [
            row["Filename"]
            for row in csv_rows
            if row.get("Generate", "").strip().lower() in _YES_VALUES
        ]
        if stacks_filter is not None:
            filenames_from_csv = [
                f for f in filenames_from_csv if _filename_to_stack_name(f) in stacks_filter
            ]
        return [_to_ztier(f, z_tier) for f in filenames_from_csv]

    if p.suffix.lower() == ".txt" and p.exists():
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if stacks_filter is not None:
            lines = [f for f in lines if _filename_to_stack_name(f) in stacks_filter]
        return [_to_ztier(f, z_tier) for f in lines]

    # Chain spec / regex pattern modes
    tokens = [t.strip() for t in variants_arg.split(",") if t.strip()]

    if any("-" in t or _is_chain_pattern(t) for t in tokens):
        # Mode 3: strip any embedded z-tier from each token, prepend the target z_tier, then expand
        filenames: List[str] = []
        for t in tokens:
            normalised = re.sub(r"^z(100|25|6|2)-", "", t)
            full = f"{z_tier}-{normalised}"
            if _is_chain_pattern(full):
                for spec_str in expand_chain_pattern(full):
                    spec = parse_full_chain_spec(spec_str)
                    if spec is not None:
                        filenames.extend(_expand_chain_spec_to_all_stacks(spec, source, stacks_filter))
            else:
                spec = parse_full_chain_spec(full)
                if spec is not None:
                    filenames.extend(_expand_chain_spec_to_all_stacks(spec, source, stacks_filter))
                else:
                    logging.warning("Cannot parse chain spec '%s', skipping", t)
        return filenames

    # Mode 1/2: preset level or comma-separated IDs → cross-product
    enfuse_ids, tmo_ids, grading_ids, _ct_ids = expand_variants(variants_arg)
    if not grading_ids:
        grading_ids = list(GRADING_PRESETS.keys())

    filenames = []
    for e in enfuse_ids:
        for g in grading_ids:
            spec = parse_full_chain_spec(f"{z_tier}-{e}-{g}")
            if spec is not None:
                filenames.extend(_expand_chain_spec_to_all_stacks(spec, source, stacks_filter))
        for t_id in tmo_ids:
            for g in grading_ids:
                spec = parse_full_chain_spec(f"{z_tier}-{e}-{t_id}-{g}")
                if spec is not None:
                    filenames.extend(_expand_chain_spec_to_all_stacks(spec, source, stacks_filter))

    if not filenames and enfuse_ids:
        logging.warning("No stacks found for variants spec '%s'", variants_arg)
    elif not enfuse_ids:
        logging.warning("No valid variant IDs in spec '%s'", variants_arg)
    return filenames


def _generate_one(
    filename: str,
    spec: ChainSpec,
    source: Path,
    raw_converter: Optional[str],
    quality: int,
    resolution: Optional[int],
    redo: bool,
) -> bool:
    """Execute chain steps for one target filename. Returns True if newly generated."""
    fname = Path(filename).name
    if not redo:
        full_res_copies = [d / fname for d in source.glob("out-*/") if (d / fname).exists()]
        resized_exists = resolution is None or (source / f"out-{resolution}" / fname).exists()
        if full_res_copies and resized_exists:
            return False
        # Full-res exists but resized copy is missing — resize from existing copy
        if full_res_copies and not resized_exists and resolution is not None:
            from .export import export_at_resolution
            export_at_resolution(full_res_copies[0], source, resolution, quality=quality, redo=redo)
            return True

    # Derive stack dir from filename convention.
    # Old-style: YYYYMMDDHHMMSS-CCCxxx-NNNN-z25-...  → NNNN-stack/
    # Named:     YYYYMMDDHHMMSS-CCCxxx-NNNN-shrt-z25-...  → NNNN-shrt/
    parts = filename.split("-")
    if len(parts) < 4:
        logging.warning("Cannot derive stack dir from %s", filename)
        return False
    stack_dir_name = _filename_to_stack_name(filename)
    if not stack_dir_name:
        logging.warning("Cannot derive stack dir from %s", filename)
        return False
    stack_dir = source / stack_dir_name
    if not stack_dir.is_dir():
        logging.warning("Stack dir not found: %s", stack_dir)
        return False

    # Find source ARWs in stack dir
    arws = sorted(stack_dir.glob("*.arw")) + sorted(stack_dir.glob("*.ARW"))
    if not arws:
        logging.warning("No ARW files in %s", stack_dir)
        return False

    if raw_converter is None:
        logging.error("No raw converter available for %s", filename)
        return False

    # Combined outputs live in the z-tier subfolder (mirrors process_stack layout)
    out_base = stack_dir_to_filename_base(stack_dir.name)  # e.g. "20260411152701-m4aens-2324" or with shorthand
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
        return False

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
            return False

    # Step 3: enfuse — temp TIF goes into z_dir
    enfuse_tif = z_dir / f"{out_base}-{spec.z_tier}-{spec.enfuse_id}.tif"
    ok = run_enfuse(aligned, enfuse_tif, spec.enfuse_id, redo=redo)
    if not ok:
        logging.error("Enfuse failed for %s", filename)
        return False

    # Step 4: TMO (optional) — temp JPG goes into z_dir
    if spec.tmo_id:
        tmo_jpg = z_dir / f"{out_base}-{spec.z_tier}-{spec.enfuse_id}-{spec.tmo_id}.jpg"
        ok = run_tmo(enfuse_tif, tmo_jpg, spec.tmo_id, quality, redo=redo)
        if not ok:
            logging.error("TMO failed for %s", filename)
            return False
        grading_src = tmo_jpg
    else:
        grading_src = enfuse_tif

    # Step 5: grading — staged final JPG also goes into z_dir.
    # Always regenerate so discover-annotated intermediates are never exported.
    out_name = Path(filename).name
    final_jpg = z_dir / out_name
    ok = apply_grading(grading_src, final_jpg, spec.grading_id, quality, redo=True, ct_id=spec.ct_id)
    if not ok:
        logging.error("Grading failed for %s", filename)
        return False

    # Copy EXIF from middle ARW
    mid_arw = arws[len(arws) // 2]
    from .processing import _copy_exif
    _copy_exif(mid_arw, final_jpg)

    # Step 6: export to out-BBBB/ folder(s)
    _export_variants([final_jpg], source, resolution=resolution, quality=quality, redo=redo)
    logging.info("Generated: %s", filename)
    return True


# ---------------------------------------------------------------------------
# Enhance ARWs
# ---------------------------------------------------------------------------


@_timed_cmd
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


@_timed_cmd
def cmd_cleanup(source: Path) -> None:
    """Remove z-tier discovery folders and the variants/ folder — see README.md § cleanup."""
    removed = 0
    for stack_dir in find_stack_dirs(source):
        for z_dir in stack_dir.iterdir():
            if z_dir.is_dir() and z_dir.name in Z_TIERS:
                shutil.rmtree(z_dir)
                removed += 1

    variants_dir = source / "variants"
    if variants_dir.exists():
        shutil.rmtree(variants_dir)
        removed += 1

    logging.info("Cleanup removed %d directories", removed)


# ---------------------------------------------------------------------------
# Full workflow
# ---------------------------------------------------------------------------


def _detect_workflow_progress(source: Path) -> dict:
    """Detect completed workflow steps from filesystem state and ppsp.log."""
    state: dict = {
        "rename": False,
        "organize": False,
        "cull": False,
        "prune": False,
        "name": False,
        "discover": False,
        "generate": False,
    }

    csv_path = source / _PHOTOS_CSV
    if csv_path.exists():
        state["rename"] = True

    stack_dirs = find_stack_dirs(source)
    if stack_dirs:
        state["organize"] = True

    cull_dir = source / "cull"
    cull_previews = list(cull_dir.glob("*.jpg")) if cull_dir.exists() else []
    if cull_previews:
        state["cull"] = True

    # Prune is considered done when every surviving stack has a cull preview.
    if state["cull"] and stack_dirs:
        cull_bases = {p.name.split("_count")[0] for p in cull_previews}
        stack_names = {d.name for d in stack_dirs}
        if stack_names and stack_names.issubset(cull_bases):
            state["prune"] = True

    stacks_csv = source / STACKS_CSV
    if stacks_csv.exists():
        _srows = load_stacks_csv(source)
        if any(r.get("Title") for r in _srows):
            state["name"] = True

    variants_dir = source / "variants"
    if variants_dir.exists() and list(variants_dir.glob("*.jpg")):
        state["discover"] = True

    if any((source / d).glob("*.jpg") for d in source.glob("out*/") if d.is_dir()):
        state["generate"] = True

    # Supplement with log evidence (look for completion markers)
    log_path = source / "ppsp.log"
    if log_path.exists():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="ignore")
            if "Stack organization complete" in log_text:
                state["organize"] = True
            if "Cull preview:" in log_text:
                state["cull"] = True
            if "Prune complete" in log_text and not stack_dirs or state["prune"]:
                state["prune"] = True
            if "Variant discovery complete" in log_text:
                state["discover"] = True
            if "Generate complete" in log_text or "variants already exist" in log_text:
                state["generate"] = True
        except OSError:
            pass

    return state


def _open_viewer(viewer: str, path: Path) -> None:
    """Open a path in the viewer app non-blocking."""
    import subprocess as _sp
    try:
        _sp.Popen([viewer, str(path)])
    except OSError as exc:
        logging.warning("Could not open viewer '%s': %s", viewer, exc)


def run_full_workflow(
    source: Path,
    gap: float = 30.0,
    quality: int = 80,
    resolution: Optional[int] = None,
    batch: bool = False,
    verbose: bool = False,
    redo: bool = False,
    default_model: str = "",
    default_lens: str = "",
    variants_arg: str = "some",
    discover_z_tier: str = "z25",
    generate_z_tier: str = "z100",
    viewer: str = "xdg-open",
    interactive: bool = False,
) -> None:
    """Run all steps in sequence, prompting between each unless --batch — see design.md § Workflow."""

    def _prompt(msg: str) -> bool:
        if batch:
            return True
        ans = input(f"{msg} [Y/n]: ").strip().lower()
        return ans != "n"

    logging.info("=== Full workflow starting ===")

    # Auto-detect progress so a resumed run can skip already-completed steps.
    if not batch and not redo:
        progress = _detect_workflow_progress(source)
        completed = [k for k, v in progress.items() if v]
        if completed:
            logging.info("Progress detected: %s already done.", ", ".join(completed))
            step_order = ["rename", "organize", "cull", "prune", "name", "discover", "generate"]
            first_pending = next((s for s in step_order if not progress[s]), None)
            if first_pending:
                logging.info("Resuming from: %s", first_pending)
                # If prune is done but discover is not, offer choice to re-cull or proceed.
                if progress["prune"] and not progress["discover"]:
                    ans = input(
                        "Cull and prune already done. Proceed to stack naming/variant discovery? "
                        "[Y/n, or 'r' to re-cull stacks]: "
                    ).strip().lower()
                    if ans == "r":
                        first_pending = "cull"
                    elif ans == "n":
                        logging.info("Aborted by user.")
                        return
                else:
                    ans = input(
                        f"Resume from '{first_pending}'? [Y/n]: "
                    ).strip().lower()
                    if ans == "n":
                        first_pending = None  # run everything

                # Skip completed steps
                if first_pending is not None:
                    for step in step_order:
                        if step == first_pending:
                            break
                        progress[f"_skip_{step}"] = True
        else:
            progress = {}

        skip = lambda step: progress.get(f"_skip_{step}", False)
    else:
        skip = lambda step: False

    if not skip("rename") and _prompt("Step 1: Rename and catalogue"):
        cmd_rename([], source, default_model=default_model, default_lens=default_lens, redo=redo)

    if not skip("organize") and _prompt("Step 2: Organize stacks"):
        cmd_organize([], source, gap=gap, redo=redo)

    if not skip("cull") and _prompt("Step 3: Generate culling previews"):
        cmd_cull(source, quality=quality, redo=redo)

    if not skip("cull") and not batch:
        cull_dir = source / "cull"
        if cull_dir.exists():
            logging.info("Step 4: Review cull previews, delete unwanted stacks.")
            _open_viewer(viewer, cull_dir)
        input("Press Enter when culling is done...")

    if not skip("prune") and _prompt("Step 5: Prune rejected stacks"):
        cmd_prune(source)

    if not skip("name") and _prompt("Step 6: Name stacks (optional; press n to skip)"):
        cmd_name(source, batch=batch, redo=redo)

    if not skip("discover") and _prompt("Step 7: Variant discovery"):
        if interactive and not batch:
            from .interactive import run_interactive_discovery
            run_interactive_discovery(
                source,
                z_tier=discover_z_tier,
                quality=quality,
                redo=redo,
                viewer=viewer,
            )
        else:
            cmd_discover(source, variants_arg=variants_arg, z_tier=discover_z_tier, quality=quality, redo=redo)

    selection_method = "folder"
    if not skip("discover") and not batch:
        variants_dir = source / "variants"
        logging.info("")
        logging.info("Step 8 — Variant selection. Choose a method:")
        logging.info("  1. Folder-based (default): delete unwanted files from %s/", variants_dir)
        logging.info("     then run --generate variants/ (hard-linked to stack z-tier subfolders)")
        logging.info("  2. CSV-based: edit ppsp_generate.csv, mark keepers with x/y/+ in Generate column")
        if variants_dir.exists():
            _open_viewer(viewer, variants_dir)
        ans = input("Method [1/2, default=1]: ").strip()
        selection_method = "csv" if ans == "2" else "folder"
        input("Press Enter when selection is done...")

    if not skip("generate") and _prompt("Step 9: Generate selected variants"):
        if selection_method == "csv":
            gen_csv = source / _GENERATE_CSV
            if gen_csv.exists():
                cmd_generate(source, variants_arg=str(gen_csv), z_tier=generate_z_tier, quality=quality, resolution=resolution, redo=redo)
            else:
                logging.warning("ppsp_generate.csv not found; skipping generate step")
        else:
            variants_dir = source / "variants"
            if variants_dir.exists():
                cmd_generate(source, variants_arg=str(variants_dir), z_tier=generate_z_tier, quality=quality, resolution=resolution, redo=redo)
            else:
                logging.warning("variants/ folder not found; skipping generate step")

    logging.info("=== Full workflow complete ===")
