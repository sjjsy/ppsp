"""Export helpers for out_full/ and out_web/ — see README.md § Output structure."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from .util import run_command


def copy_to_full(src: Path, out_full_dir: Path, redo: bool = False) -> None:
    """Copy a variant to out_full/, skipping if it already exists — see README.md § Step 7."""
    out_full_dir.mkdir(parents=True, exist_ok=True)
    dst = out_full_dir / src.name
    if dst.exists() and not redo:
        return
    shutil.copy2(src, dst)


def make_web_copy(src: Path, out_web_dir: Path, quality: int = 80, redo: bool = False) -> None:
    """Resize to 2048px max and write a -web copy to out_web/ — see README.md § Step 7."""
    out_web_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    ext = src.suffix
    web_name = f"{stem}-web{ext}"
    dst = out_web_dir / web_name
    if dst.exists() and not redo:
        return
    cmd = [
        "convert", str(src),
        "-resize", "2048x2048>",
        "-quality", str(quality),
        "-strip",
        str(dst),
    ]
    run_command(cmd, f"web copy {src.name}")


def export_variants(variant_paths: List[Path], source_dir: Path, redo: bool = False) -> None:
    """Copy each variant to out_full/ and produce a web copy in out_web/ — see README.md § Step 7."""
    out_full = source_dir / "out_full"
    out_web = source_dir / "out_web"
    for vpath in variant_paths:
        copy_to_full(vpath, out_full, redo=redo)
        make_web_copy(vpath, out_web, redo=redo)
