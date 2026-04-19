"""Per-stack image processing: RAW conversion, alignment, enfuse, TMO, grading — see README.md § Step 5."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional

from .models import Photo, StackType
from .util import run_command
from .variants import ENFUSE_FOCUS, ENFUSE_VARIANTS, GRADING_PRESETS, TMO_VARIANTS

_RAW_EXTS = frozenset({".arw", ".raw", ".cr2", ".nef", ".dng"})


def _pick_best_companion(photos: List[Photo]) -> Photo:
    raw = [p for p in photos if p.ext in _RAW_EXTS]
    candidates = raw if raw else photos
    return max(candidates, key=lambda p: p.path.stat().st_size if p.path.exists() else 0)


def _deduplicate_companions(photos: List[Photo]) -> List[Photo]:
    """Keep one file per stem, preferring raw formats over JPEG companions."""
    by_stem: Dict[str, List[Photo]] = defaultdict(list)
    for p in photos:
        by_stem[Path(p.filename).stem].append(p)
    result = [_pick_best_companion(group) for group in by_stem.values()]
    result.sort(key=lambda p: p.timestamp)
    return result


def convert_raw_to_tiff(
    arw: Path,
    out_tif: Path,
    z_tier: str,
    raw_converter: str,
    redo: bool = False,
) -> bool:
    """Convert an ARW file to a 16-bit TIFF at the requested z-tier — see README.md § Resolution tiers."""
    if out_tif.exists() and not redo:
        return True

    half_size = z_tier in ("z25", "z13")

    if raw_converter == "dcraw":
        cmd = ["dcraw", "-T", "-4", "-w", "-q", "3", "-M"]
        if half_size:
            cmd.append("-h")
        cmd.append(str(arw))
        run_command(cmd, f"dcraw {z_tier} for {arw.name}")
        # dcraw writes <stem>.tiff next to the input
        dcraw_out = arw.with_suffix(".tiff")
        if not dcraw_out.exists():
            logging.error("dcraw did not produce %s", dcraw_out)
            return False
        dcraw_out.rename(out_tif)
    else:
        # darktable-cli fallback
        run_command(
            ["darktable-cli", str(arw), str(out_tif)],
            f"darktable-cli {z_tier} for {arw.name}",
        )

    if not out_tif.exists():
        return False

    if z_tier == "z13":
        run_command(["mogrify", "-resize", "50%", str(out_tif)], "mogrify 50% for z13")

    return out_tif.exists()


def align_stack(
    tiff_files: List[Path],
    prefix: str,
    is_hdr: bool = True,
    redo: bool = False,
) -> List[Path]:
    """Run align_image_stack and return sorted aligned_*.tif list — see DESIGN.md § align_image_stack."""
    prefix_path = Path(prefix)
    existing = sorted(prefix_path.parent.glob(f"{prefix_path.name}*.tif"))
    if existing and not redo:
        return existing

    cmd = ["align_image_stack", "-a", prefix, "-v"]
    if not is_hdr:
        cmd.append("-m")
    cmd.extend(str(f) for f in tiff_files)
    run_command(cmd, "align_image_stack")

    return sorted(prefix_path.parent.glob(f"{prefix_path.name}*.tif"))


def run_enfuse(
    aligned: List[Path],
    output_tif: Path,
    enfuse_id: str,
    redo: bool = False,
) -> bool:
    """Run enfuse with the given variant params — see README.md § Enfuse variants."""
    if output_tif.exists() and not redo:
        return True

    params = ENFUSE_FOCUS if enfuse_id == "focu" else ENFUSE_VARIANTS.get(enfuse_id, [])
    cmd = ["enfuse", "-o", str(output_tif), "--compression=none"] + params
    cmd.extend(str(f) for f in aligned)
    run_command(cmd, f"enfuse {enfuse_id}")
    return output_tif.exists()


def run_tmo(
    enfuse_tif: Path,
    temp_jpg: Path,
    tmo_id: str,
    quality: int,
    redo: bool = False,
) -> bool:
    """Run luminance-hdr-cli TMO on an enfuse TIFF — see README.md § Tone-mapping operators."""
    if temp_jpg.exists() and not redo:
        return True

    tmo_flags = TMO_VARIANTS.get(tmo_id, [])
    cmd = (
        ["luminance-hdr-cli", "-l", str(enfuse_tif), "-o", str(temp_jpg)]
        + tmo_flags
        + ["-q", str(quality)]
    )
    run_command(cmd, f"luminance-hdr-cli {tmo_id}")
    return temp_jpg.exists()


def apply_grading(
    src: Path,
    dst_jpg: Path,
    grading_id: str,
    quality: int,
    redo: bool = False,
) -> bool:
    """Apply an ImageMagick grading preset to produce the final JPG — see README.md § Color-grading presets."""
    if dst_jpg.exists() and not redo:
        return True

    grading_args = GRADING_PRESETS.get(grading_id, [])
    cmd = (
        ["convert", str(src)]
        + grading_args
        + ["-quality", str(quality), str(dst_jpg)]
    )
    run_command(cmd, f"grading {grading_id}")
    return dst_jpg.exists()


def _copy_exif(source: Path, dest: Path) -> None:
    """Copy all EXIF tags from source to dest with exiftool — see DESIGN.md § EXIF preservation."""
    run_command(
        ["exiftool", "-TagsFromFile", str(source), "-all:all", "-overwrite_original", str(dest)],
        "copy EXIF",
        check=False,
    )


def create_jpg_from_arw(
    arw: Path,
    jpg_path: Path,
    quality: int,
    raw_converter: str,
    redo: bool = False,
) -> bool:
    """Convert a single ARW to an enhanced JPG — see README.md § arws-enhance."""
    if jpg_path.exists() and not redo:
        return True

    if raw_converter == "dcraw":
        pipeline = (
            f'dcraw -4 -c -w -H 2 -q 3 "{arw}" | '
            f'convert - -colorspace sRGB -sigmoidal-contrast 4,50% '
            f'-unsharp 0x1.2+1.5+0.05 -quality {quality} "{jpg_path}"'
        )
        run_command(pipeline, "dcraw + ImageMagick enhance", shell=True)
    else:
        run_command(["darktable-cli", str(arw), str(jpg_path)], "darktable-cli enhance")

    if not jpg_path.exists():
        return False

    _copy_exif(arw, jpg_path)
    return jpg_path.exists()


def create_collage(
    stack_dir: Path,
    stack_name: str,
    all_variants: List[str],
    source_photos: List[Photo],
    redo: bool = False,
) -> None:
    """Assemble a labeled collage from originals + enfuse + TMO variants — see README.md § Collage."""
    collage_path = stack_dir / f"{stack_name}-collage.jpg"
    if collage_path.exists() and not redo:
        return

    tile_size = "640x640"

    def labeled_tile(src: Path, label: str, dst: Path) -> Optional[Path]:
        if not src.exists():
            return None
        cmd = [
            "convert", str(src),
            "-resize", f"{tile_size}>",
            "-background", "black",
            "-extent", tile_size,
            "-font", "Liberation-Sans",
            "-fill", "white",
            "-undercolor", "#00000080",
            "-pointsize", "18",
            "-gravity", "South",
            "-annotate", "+0+5", label,
            str(dst),
        ]
        run_command(cmd, f"tile {label}", check=False)
        return dst if dst.exists() else None

    tile_dir = stack_dir / "_tiles"
    tile_dir.mkdir(exist_ok=True)

    rows: List[List[Path]] = []

    # Row 1: originals
    orig_tiles: List[Path] = []
    for i, photo in enumerate(source_photos):
        tile = tile_dir / f"orig_{i:03d}.jpg"
        result = labeled_tile(photo.path, photo.filename, tile)
        if result:
            orig_tiles.append(result)
    if orig_tiles:
        rows.append(orig_tiles)

    # Collect variant JPGs present in the stack dir
    enfuse_tiles: List[Path] = []
    tmo_tiles: List[Path] = []

    for variant_name in sorted(all_variants):
        vpath = stack_dir / variant_name
        if not vpath.exists():
            continue
        stem = Path(variant_name).stem
        parts = stem.split("-")
        # z-tier at index 3, enfuse at 4, possible tmo at 5
        chain_parts = parts[3:] if len(parts) > 3 else []
        has_tmo = len(chain_parts) >= 3 and chain_parts[2] in TMO_VARIANTS

        tile = tile_dir / f"var_{variant_name}"
        result = labeled_tile(vpath, stem, tile)
        if not result:
            continue
        if has_tmo:
            tmo_tiles.append(result)
        else:
            enfuse_tiles.append(result)

    if enfuse_tiles:
        rows.append(enfuse_tiles)
    if tmo_tiles:
        rows.append(tmo_tiles)

    if not rows:
        logging.warning("No tiles found for collage in %s", stack_dir)
        shutil.rmtree(tile_dir, ignore_errors=True)
        return

    row_images: List[Path] = []
    for idx, row_tiles in enumerate(rows):
        row_img = tile_dir / f"row_{idx:02d}.jpg"
        cmd = ["convert", "+append"] + [str(t) for t in row_tiles] + [str(row_img)]
        run_command(cmd, f"collage row {idx}", check=False)
        if row_img.exists():
            row_images.append(row_img)

    if row_images:
        cmd = ["convert", "-append"] + [str(r) for r in row_images] + [
            "-resize", "3840x3840>",
            str(collage_path),
        ]
        run_command(cmd, "assemble collage", check=False)

    shutil.rmtree(tile_dir, ignore_errors=True)


def process_stack(
    stack_dir: Path,
    stack_name: str,
    stack_type: StackType,
    enfuse_ids: List[str],
    tmo_ids: List[str],
    z_tier: str,
    quality: int,
    source_photos: List[Photo],
    redo: bool = False,
) -> List[str]:
    """Orchestrate the full per-stack variant discovery pipeline — see README.md § Step 5.

    Returns list of generated variant filenames (relative to stack_dir).
    """
    if not source_photos:
        logging.warning("No source photos for stack %s", stack_name)
        return []

    source_photos = _deduplicate_companions(source_photos)

    raw_converter = _get_raw_converter_lazy()

    # 1. Convert ARW → TIFF
    tiff_files: List[Path] = []
    for photo in source_photos:
        arw = photo.path
        if arw.suffix.lower() not in _RAW_EXTS:
            logging.warning("Skipping non-raw file %s in align_image_stack input", arw.name)
            continue
        if raw_converter is None:
            logging.error("No raw converter available")
            return []
        out_tif = stack_dir / f"{arw.stem}.tif"
        ok = convert_raw_to_tiff(arw, out_tif, z_tier, raw_converter, redo=redo)
        if ok:
            tiff_files.append(out_tif)
        else:
            logging.error("Failed to convert %s", arw.name)
            return []

    if len(tiff_files) < 2:
        logging.warning("Fewer than 2 TIFFs for stack %s, skipping alignment", stack_name)
        return []

    # 2. Align
    align_prefix = str(stack_dir / "aligned_")
    is_hdr = stack_type == StackType.HDR
    aligned = align_stack(tiff_files, align_prefix, is_hdr=is_hdr, redo=redo)
    if not aligned:
        logging.error("Alignment failed for %s", stack_name)
        return []

    # 3-5. Enfuse × TMO × Grading
    generated: List[str] = []

    # middle image for EXIF
    mid_photo = source_photos[len(source_photos) // 2]

    if stack_type == StackType.FOCUS:
        # Single focu enfuse variant
        _run_focus_variants(
            aligned, stack_dir, stack_name, z_tier, quality, mid_photo, redo, generated
        )
    else:
        _run_hdr_variants(
            aligned, stack_dir, stack_name, z_tier, enfuse_ids, tmo_ids,
            quality, mid_photo, redo, generated
        )

    # Collage
    create_collage(stack_dir, stack_name, generated, source_photos, redo=redo)
    return generated


def _get_raw_converter_lazy() -> Optional[str]:
    from .util import get_raw_converter
    return get_raw_converter()


def _run_focus_variants(
    aligned: List[Path],
    stack_dir: Path,
    stack_name: str,
    z_tier: str,
    quality: int,
    mid_photo: Photo,
    redo: bool,
    generated: List[str],
) -> None:
    """Run the single focus-stack enfuse + grading chain — see README.md § Enfuse variants."""
    from .variants import GRADING_PRESETS

    enfuse_tif = stack_dir / f"temp_focu.tif"
    ok = run_enfuse(aligned, enfuse_tif, "focu", redo=redo)
    if not ok:
        return

    for grading_id in GRADING_PRESETS:
        out_name = f"{_base_name(stack_name)}-{z_tier}-focu-{grading_id}.jpg"
        out_path = stack_dir / out_name
        ok = apply_grading(enfuse_tif, out_path, grading_id, quality, redo=redo)
        if ok:
            _copy_exif(mid_photo.path, out_path)
            generated.append(out_name)


def _run_hdr_variants(
    aligned: List[Path],
    stack_dir: Path,
    stack_name: str,
    z_tier: str,
    enfuse_ids: List[str],
    tmo_ids: List[str],
    quality: int,
    mid_photo: Photo,
    redo: bool,
    generated: List[str],
) -> None:
    """Run all enfuse × TMO × grading combinations for an HDR stack — see README.md § Variant levels."""
    from .variants import GRADING_PRESETS

    base = _base_name(stack_name)

    for enfuse_id in enfuse_ids:
        enfuse_tif = stack_dir / f"temp_{enfuse_id}.tif"
        ok = run_enfuse(aligned, enfuse_tif, enfuse_id, redo=redo)
        if not ok:
            continue

        # Enfuse-only grading (no TMO)
        for grading_id in GRADING_PRESETS:
            out_name = f"{base}-{z_tier}-{enfuse_id}-{grading_id}.jpg"
            out_path = stack_dir / out_name
            ok2 = apply_grading(enfuse_tif, out_path, grading_id, quality, redo=redo)
            if ok2:
                _copy_exif(mid_photo.path, out_path)
                generated.append(out_name)

        # TMO variants
        for tmo_id in tmo_ids:
            tmo_jpg = stack_dir / f"temp_{enfuse_id}_{tmo_id}.jpg"
            ok3 = run_tmo(enfuse_tif, tmo_jpg, tmo_id, quality, redo=redo)
            if not ok3:
                continue

            for grading_id in GRADING_PRESETS:
                out_name = f"{base}-{z_tier}-{enfuse_id}-{tmo_id}-{grading_id}.jpg"
                out_path = stack_dir / out_name
                ok4 = apply_grading(tmo_jpg, out_path, grading_id, quality, redo=redo)
                if ok4:
                    _copy_exif(mid_photo.path, out_path)
                    generated.append(out_name)


def _base_name(stack_name: str) -> str:
    """Strip the -stack suffix to get the base photo identifier."""
    if stack_name.endswith("-stack"):
        return stack_name[: -len("-stack")]
    return stack_name
