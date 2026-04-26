"""Export helpers — outputs go to outBBBB/ folders named by long-side pixel count."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from .util import run_command


def _get_long_side(path: Path) -> Optional[int]:
    """Return the longer dimension of an image in pixels, or None on failure."""
    try:
        result = subprocess.run(
            ["identify", "-format", "%w %h", str(path)],
            capture_output=True, text=True, check=True,
        )
        w, h = map(int, result.stdout.strip().split())
        return max(w, h)
    except Exception:
        return None


def export_at_full_res(src: Path, shoot_dir: Path, redo: bool = False) -> Optional[Path]:
    """Copy src to out-BBBB/ where BBBB is its actual long-side pixel count.

    Returns the destination path, or None if the long side cannot be determined.
    """
    long_side = _get_long_side(src)
    if long_side is None:
        return None
    out_dir = shoot_dir / f"out-{long_side}"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / src.name
    if dst.exists() and not redo:
        return dst
    import shutil
    shutil.copy2(src, dst)
    return dst


def export_at_resolution(
    src: Path,
    shoot_dir: Path,
    long_side: int,
    quality: int = 80,
    redo: bool = False,
) -> Path:
    """Resize src to long_side pixels (shrink-only) and write to out-{long_side}/.

    The resized copy has metadata stripped for web delivery.
    Returns the destination path.
    """
    out_dir = shoot_dir / f"out-{long_side}"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / src.name
    if dst.exists() and not redo:
        return dst
    cmd = [
        "convert", str(src),
        "-resize", f"{long_side}x{long_side}>",
        "-quality", str(quality),
        "-strip",
        str(dst),
    ]
    run_command(cmd, f"resize {long_side}px {src.name}")
    return dst


def export_variants(
    variant_paths: List[Path],
    shoot_dir: Path,
    resolution: Optional[int] = None,
    quality: int = 80,
    redo: bool = False,
) -> None:
    """Export each variant to its out-BBBB/ folder.

    Always writes the full z-tier copy to out-{actual_long_side}/.
    If resolution is given, also writes a resized copy to out-{resolution}/.
    """
    for vpath in variant_paths:
        export_at_full_res(vpath, shoot_dir, redo=redo)
        if resolution is not None:
            export_at_resolution(vpath, shoot_dir, resolution, quality=quality, redo=redo)
