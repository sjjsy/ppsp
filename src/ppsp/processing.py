"""Per-stack image processing: RAW conversion, alignment, enfuse, TMO, grading — see README.md § Step 5."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional

from .models import ChainSpec, Photo, StackType
from .util import run_command
from .variants import CT_PRESETS, ENFUSE_FOCUS, ENFUSE_VARIANTS, GRADING_PRESETS, TMO_VARIANTS

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


def _z25_sibling_of_z6(z6_tif: Path) -> Optional[Path]:
    """Return the z25 counterpart path for a z6 TIFF, or None if the name lacks '-z6'."""
    name = z6_tif.name
    if "-z6" in name:
        return z6_tif.with_name(name.replace("-z6", "-z25", 1))
    return None


def convert_raw_to_tiff(
    arw: Path,
    out_tif: Path,
    z_tier: str,
    raw_converter: str,
    redo: bool = False,
) -> bool:
    """Convert an ARW file to a 16-bit TIFF at the requested z-tier — see README.md § Resolution tiers.

    When z_tier is 'z6', the dcraw -h output (z25 quality) is also preserved as a sibling
    so that a later generate can reuse it.  z2 builds on z6 (another 50% resize).
    """
    if out_tif.exists() and not redo:
        return True

    if z_tier == "z2":
        # Produce z6 first (which also saves the z25 sibling), then downscale once more.
        z6_tif = out_tif.with_name(out_tif.name.replace("-z2.", "-z6.", 1))
        if not convert_raw_to_tiff(arw, z6_tif, "z6", raw_converter, redo=redo):
            return False
        shutil.copy2(z6_tif, out_tif)
        run_command(["mogrify", "-resize", "50%", str(out_tif)], "mogrify 50% for z2")
        return out_tif.exists()

    half_size = z_tier in ("z25", "z6")

    if raw_converter == "dcraw":
        cmd = ["dcraw", "-T", "-4", "-w", "-q", "3", "-M"]
        if half_size:
            cmd.append("-h")
        cmd.append(str(arw))
        run_command(cmd, f"dcraw {z_tier} for {arw.name}")
        dcraw_out = arw.with_suffix(".tiff")
        if not dcraw_out.exists():
            logging.error("dcraw did not produce %s", dcraw_out)
            return False

        if z_tier == "z6":
            # dcraw -h output is z25 quality; save it so future --half generates can reuse it.
            z25_tif = _z25_sibling_of_z6(out_tif)
            if z25_tif is not None and not z25_tif.exists():
                dcraw_out.rename(z25_tif)
                shutil.copy2(z25_tif, out_tif)
            else:
                dcraw_out.rename(out_tif)
            run_command(["mogrify", "-resize", "50%", str(out_tif)], "mogrify 50% for z6")
        else:
            dcraw_out.rename(out_tif)
    else:
        # darktable-cli fallback
        run_command(
            ["darktable-cli", str(arw), str(out_tif)],
            f"darktable-cli {z_tier} for {arw.name}",
        )
        if z_tier == "z6" and out_tif.exists():
            # Save a z25 copy before downscaling (darktable doesn't have a native half-size flag)
            z25_tif = _z25_sibling_of_z6(out_tif)
            if z25_tif is not None and not z25_tif.exists():
                shutil.copy2(out_tif, z25_tif)
            run_command(["mogrify", "-resize", "50%", str(out_tif)], "mogrify 50% for z6")

    if not out_tif.exists():
        return False

    return out_tif.exists()


def align_stack(
    tiff_files: List[Path],
    prefix: str,
    is_hdr: bool = True,
    redo: bool = False,
) -> List[Path]:
    """Run align_image_stack and return sorted aligned_*.tif list — see design.md § align_image_stack."""
    if len(tiff_files) < 2:
        return list(tiff_files)

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
    """Run enfuse with the given variant params — see README.md § Enfuse variants.

    For a single input frame, skips the enfuse binary and copies the frame directly
    so that downstream TMO and grading steps can still run.
    """
    if output_tif.exists() and not redo:
        return True

    if len(aligned) == 1:
        shutil.copy2(aligned[0], output_tif)
        return output_tif.exists()

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
    # TIFF is a positional arg (-l is for existing .hdr/.exr HDR files); -e 0 supplies the
    # missing EV value that luminance requires even for single-frame pseudo-HDR input.
    cmd = (
        ["luminance-hdr-cli", str(enfuse_tif), "-e", "0", "-o", str(temp_jpg)]
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
    ct_id: Optional[str] = None,
) -> bool:
    """Apply an ImageMagick grading (and optional CT) preset to produce the final JPG.

    When ct_id is given the CT args are inserted after -colorspace sRGB and before the
    grading args — matching the order established in the former warm/dv1w presets.
    See README.md § Color-temperature presets.
    """
    if dst_jpg.exists() and not redo:
        return True

    grading_args = list(GRADING_PRESETS.get(grading_id, []))

    if ct_id:
        ct_args = CT_PRESETS.get(ct_id, [])
        # Strip the leading -colorspace sRGB from grading_args (we emit it once).
        if grading_args[:2] == ["-colorspace", "sRGB"]:
            grading_args = grading_args[2:]
        merged = ["-colorspace", "sRGB"] + ct_args + grading_args
    else:
        merged = grading_args

    cmd = ["convert", str(src)] + merged + ["-quality", str(quality), str(dst_jpg)]
    run_command(cmd, f"grading {grading_id}" + (f"+{ct_id}" if ct_id else ""))
    return dst_jpg.exists()


def annotate_image(jpg: Path) -> None:
    """Overlay the full filename (stem) at bottom centre of a variant JPEG in place."""
    run_command(
        [
            "mogrify",
            "-font", "Liberation-Sans-Bold",
            "-fill", "white",
            "-undercolor", "#00000099",
            "-pointsize", "24",
            "-gravity", "South",
            "-annotate", "+0+8",
            jpg.stem,
            str(jpg),
        ],
        f"annotate {jpg.name}",
        check=False,
    )


def _copy_exif(source: Path, dest: Path) -> None:
    """Copy all EXIF tags from source to dest with exiftool — see design.md § EXIF preservation."""
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
    output_dir: Path,
    stack_name: str,
    all_variants: List[str],
    source_photos: List[Photo],
    redo: bool = False,
) -> None:
    """Assemble a labeled collage in a grid approximating 16:9 — see README.md § Collage.

    output_dir is the z-tier subfolder where variant JPGs live; the collage is written there too.
    """
    import math

    collage_path = output_dir / f"{stack_name}-collage.jpg"
    if collage_path.exists() and not redo:
        return

    TILE_W = 640  # tiles are resized to this width; height follows source aspect ratio

    def labeled_tile(src: Path, label: str, dst: Path) -> Optional[Path]:
        """Produce a resized tile with the full filename label at the bottom."""
        if not src.exists():
            return None
        cmd = [
            "convert", str(src),
            "-resize", f"{TILE_W}x>",
            "-font", "Liberation-Sans-Bold",
            "-fill", "white",
            "-undercolor", "#000000aa",
            "-pointsize", "18",
            "-gravity", "South",
            "-annotate", "+0+6", label,
            str(dst),
        ]
        run_command(cmd, f"tile {label[:30]}", check=False)
        return dst if dst.exists() else None

    tile_dir = output_dir / "_tiles"
    tile_dir.mkdir(exist_ok=True)

    all_tiles: List[Path] = []

    # Originals first; label: full filename stem
    for i, photo in enumerate(source_photos):
        tile = tile_dir / f"orig_{i:03d}.jpg"
        result = labeled_tile(photo.path, Path(photo.filename).stem, tile)
        if result:
            all_tiles.append(result)

    # Variants; label: full filename stem
    for variant_name in sorted(all_variants):
        vpath = output_dir / variant_name
        if not vpath.exists():
            continue
        tile = tile_dir / f"var_{variant_name}"
        result = labeled_tile(vpath, Path(variant_name).stem, tile)
        if result:
            all_tiles.append(result)

    if not all_tiles:
        logging.warning("No tiles found for collage in %s", output_dir)
        shutil.rmtree(tile_dir, ignore_errors=True)
        return

    # Find n_cols that makes the grid aspect ratio closest to 16:9.
    # Camera tiles are ~3:2, so assumed tile height = TILE_W * 2/3.
    assumed_tile_h = TILE_W * 2.0 / 3.0
    target_ratio = 1920.0 / 1080.0
    n = len(all_tiles)
    best_cols, best_diff = 1, float("inf")
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        ratio = (cols * TILE_W) / (rows * assumed_tile_h)
        diff = abs(ratio - target_ratio)
        if diff < best_diff:
            best_diff = diff
            best_cols = cols
    n_cols = best_cols
    n_rows = math.ceil(n / n_cols)

    row_images: List[Path] = []
    for r in range(n_rows):
        row_tiles = all_tiles[r * n_cols: (r + 1) * n_cols]
        row_img = tile_dir / f"row_{r:02d}.jpg"
        cmd = ["convert", "+append"] + [str(t) for t in row_tiles] + [str(row_img)]
        run_command(cmd, f"collage row {r}", check=False)
        if row_img.exists():
            row_images.append(row_img)

    if row_images:
        cmd = ["convert", "-append"] + [str(r) for r in row_images] + [str(collage_path)]
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
    grading_ids: Optional[List[str]] = None,
    ct_ids: Optional[List[str]] = None,
    chain_specs: Optional[List[ChainSpec]] = None,
    redo: bool = False,
) -> List[str]:
    """Orchestrate the full per-stack variant discovery pipeline — see README.md § Step 5.

    Returns list of generated variant filenames (relative to the z-tier output subfolder).
    """
    if not source_photos:
        logging.warning("No source photos for stack %s", stack_name)
        return []

    source_photos = _deduplicate_companions(source_photos)

    raw_converter = _get_raw_converter_lazy()

    # 1. Convert ARW → TIFF (intermediates stay in stack_dir)
    tiff_files: List[Path] = []
    for photo in source_photos:
        arw = photo.path
        if arw.suffix.lower() not in _RAW_EXTS:
            logging.warning("Skipping non-raw file %s in align_image_stack input", arw.name)
            continue
        if raw_converter is None:
            logging.error("No raw converter available")
            return []
        out_tif = stack_dir / f"{arw.stem}-{z_tier}.tif"
        ok = convert_raw_to_tiff(arw, out_tif, z_tier, raw_converter, redo=redo)
        if ok:
            tiff_files.append(out_tif)
        else:
            logging.error("Failed to convert %s", arw.name)
            return []

    # Final variants + all combined outputs go into stack_dir/{z_tier}/
    output_dir = stack_dir / z_tier
    output_dir.mkdir(exist_ok=True)

    # 2. Align — skipped for single-frame stacks; prefix in output_dir
    if len(tiff_files) < 2:
        logging.info("Single-frame stack %s — skipping alignment", stack_name)
        aligned = tiff_files
    else:
        align_prefix = str(output_dir / f"{_base_name(stack_name)}-{z_tier}-aligned")
        is_hdr = stack_type == StackType.HDR
        aligned = align_stack(tiff_files, align_prefix, is_hdr=is_hdr, redo=redo)
        if not aligned:
            logging.error("Alignment failed for %s", stack_name)
            return []

    effective_gradings = grading_ids if grading_ids is not None else list(GRADING_PRESETS.keys())
    effective_cts = ct_ids if ct_ids is not None else []

    # 3-5. Enfuse × TMO × Grading × CT
    generated: List[str] = []
    mid_photo = source_photos[len(source_photos) // 2]

    if chain_specs:
        _run_chain_specs(
            aligned, output_dir, stack_name, z_tier,
            chain_specs, quality, mid_photo, redo, generated,
        )
    elif stack_type == StackType.FOCUS:
        _run_focus_variants(
            aligned, output_dir, stack_name, z_tier,
            effective_gradings, effective_cts, quality, mid_photo, redo, generated,
        )
    else:
        _run_hdr_variants(
            aligned, output_dir, stack_name, z_tier,
            enfuse_ids, tmo_ids, effective_gradings, effective_cts, quality, mid_photo, redo, generated,
        )

    # Collage lives in output_dir alongside the variants
    create_collage(output_dir, stack_name, generated, source_photos, redo=redo)
    return generated


def _run_chain_specs(
    aligned: List[Path],
    output_dir: Path,
    stack_name: str,
    z_tier: str,
    chain_specs: List[ChainSpec],
    quality: int,
    mid_photo: Photo,
    redo: bool,
    generated: List[str],
) -> None:
    """Run exactly the specified chains — no Cartesian product — see README.md § Variant levels."""
    base = _base_name(stack_name)

    for spec in chain_specs:
        enfuse_tif = output_dir / f"{base}-{z_tier}-{spec.enfuse_id}.tif"
        ok = run_enfuse(aligned, enfuse_tif, spec.enfuse_id, redo=redo)
        if not ok:
            logging.error("Enfuse failed for chain spec %s-%s-%s", spec.enfuse_id, spec.tmo_id or "", spec.grading_id)
            continue

        if spec.tmo_id:
            tmo_jpg = output_dir / f"{base}-{z_tier}-{spec.enfuse_id}-{spec.tmo_id}.jpg"
            ok = run_tmo(enfuse_tif, tmo_jpg, spec.tmo_id, quality, redo=redo)
            if not ok:
                logging.error("TMO failed for chain spec %s-%s", spec.enfuse_id, spec.tmo_id)
                continue
            grading_src = tmo_jpg
            chain_base = f"{base}-{z_tier}-{spec.enfuse_id}-{spec.tmo_id}-{spec.grading_id}"
        else:
            grading_src = enfuse_tif
            chain_base = f"{base}-{z_tier}-{spec.enfuse_id}-{spec.grading_id}"

        if spec.ct_id:
            out_name = f"{chain_base}-{spec.ct_id}.jpg"
        else:
            out_name = f"{chain_base}.jpg"

        out_path = output_dir / out_name
        newly_created = not out_path.exists() or redo
        ok = apply_grading(grading_src, out_path, spec.grading_id, quality, redo=redo, ct_id=spec.ct_id)
        if ok:
            if newly_created:
                _copy_exif(mid_photo.path, out_path)
                annotate_image(out_path)
            generated.append(out_name)


def _get_raw_converter_lazy() -> Optional[str]:
    from .util import get_raw_converter
    return get_raw_converter()


def _run_focus_variants(
    aligned: List[Path],
    output_dir: Path,
    stack_name: str,
    z_tier: str,
    grading_ids: List[str],
    ct_ids: List[str],
    quality: int,
    mid_photo: Photo,
    redo: bool,
    generated: List[str],
) -> None:
    """Run the single focus-stack enfuse + grading (+ optional CT) chain — see README.md § Enfuse variants."""
    base = _base_name(stack_name)
    enfuse_tif = output_dir / f"{base}-{z_tier}-focu.tif"
    ok = run_enfuse(aligned, enfuse_tif, "focu", redo=redo)
    if not ok:
        return

    ct_options: List[Optional[str]] = [None] + list(ct_ids)
    for grading_id in grading_ids:
        for ct_id in ct_options:
            suffix = f"-{ct_id}" if ct_id else ""
            out_name = f"{base}-{z_tier}-focu-{grading_id}{suffix}.jpg"
            out_path = output_dir / out_name
            newly_created = not out_path.exists() or redo
            ok = apply_grading(enfuse_tif, out_path, grading_id, quality, redo=redo, ct_id=ct_id)
            if ok:
                if newly_created:
                    _copy_exif(mid_photo.path, out_path)
                    annotate_image(out_path)
                generated.append(out_name)


def _run_hdr_variants(
    aligned: List[Path],
    output_dir: Path,
    stack_name: str,
    z_tier: str,
    enfuse_ids: List[str],
    tmo_ids: List[str],
    grading_ids: List[str],
    ct_ids: List[str],
    quality: int,
    mid_photo: Photo,
    redo: bool,
    generated: List[str],
) -> None:
    """Run all enfuse × TMO × grading × CT combinations for an HDR stack — see README.md § Variant levels."""
    base = _base_name(stack_name)
    ct_options: List[Optional[str]] = [None] + list(ct_ids)

    for enfuse_id in enfuse_ids:
        enfuse_tif = output_dir / f"{base}-{z_tier}-{enfuse_id}.tif"
        ok = run_enfuse(aligned, enfuse_tif, enfuse_id, redo=redo)
        if not ok:
            continue

        # Enfuse-only grading (no TMO)
        for grading_id in grading_ids:
            for ct_id in ct_options:
                suffix = f"-{ct_id}" if ct_id else ""
                out_name = f"{base}-{z_tier}-{enfuse_id}-{grading_id}{suffix}.jpg"
                out_path = output_dir / out_name
                newly_created = not out_path.exists() or redo
                ok2 = apply_grading(enfuse_tif, out_path, grading_id, quality, redo=redo, ct_id=ct_id)
                if ok2:
                    if newly_created:
                        _copy_exif(mid_photo.path, out_path)
                        annotate_image(out_path)
                    generated.append(out_name)

        # TMO variants
        for tmo_id in tmo_ids:
            tmo_jpg = output_dir / f"{base}-{z_tier}-{enfuse_id}-{tmo_id}.jpg"
            ok3 = run_tmo(enfuse_tif, tmo_jpg, tmo_id, quality, redo=redo)
            if not ok3:
                continue

            for grading_id in grading_ids:
                for ct_id in ct_options:
                    suffix = f"-{ct_id}" if ct_id else ""
                    out_name = f"{base}-{z_tier}-{enfuse_id}-{tmo_id}-{grading_id}{suffix}.jpg"
                    out_path = output_dir / out_name
                    newly_created = not out_path.exists() or redo
                    ok4 = apply_grading(tmo_jpg, out_path, grading_id, quality, redo=redo, ct_id=ct_id)
                    if ok4:
                        if newly_created:
                            _copy_exif(mid_photo.path, out_path)
                            annotate_image(out_path)
                        generated.append(out_name)


def _base_name(stack_name: str) -> str:
    """Strip the -stack suffix to get the base photo identifier."""
    if stack_name.endswith("-stack"):
        return stack_name[: -len("-stack")]
    return stack_name
