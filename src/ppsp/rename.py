"""Filename normalization and EXIF extraction — see README.md § Step 1."""

from __future__ import annotations

import csv
import io
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .util import run_command


def parse_timestamp(dt_str: str, subsec: str = "") -> Optional[datetime]:
    """Parse EXIF DateTimeOriginal + SubSecTimeOriginal into a datetime — see README.md § ppsp_photos.csv."""
    dt_str = dt_str.strip()
    subsec = subsec.strip()
    if not dt_str or dt_str == "-":
        return None
    try:
        if subsec.isdigit():
            full = f"{dt_str}.{subsec.ljust(6, '0')}"
            return datetime.strptime(full, "%Y:%m:%d %H:%M:%S.%f")
        return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def compute_refined_name(
    timestamp: Optional[datetime],
    model: str,
    lens: str,
    orig_name: str,
    target_dir: Path,
    default_model: str = "",
    default_lens: str = "",
) -> str:
    """Compute the canonical filename per README.md § Naming scheme.

    CCC = last 3 chars of model, LLL = last 3 chars of lens/serial, NNNN = last 4 digits
    from the numeric run in orig_name.  Collision suffix a/b/c... checked against target_dir.
    """
    model = model.strip() or default_model.strip()
    lens = lens.strip() or default_lens.strip()

    date_str = timestamp.strftime("%Y%m%d%H%M%S") if timestamp else "00000000000000"

    ccc = model[-3:].lower() if len(model) >= 3 else "zzz"
    lll = lens[-3:].lower() if len(lens) >= 3 else "zzz"

    digits = re.findall(r"\d+", orig_name)
    if digits:
        last_run = digits[-1]
        nnnn = last_run[-4:].zfill(4) if len(last_run) <= 4 else last_run[-4:]
    else:
        nnnn = "0000"

    base = f"{date_str}-{ccc}{lll}-{nnnn}"
    ext = Path(orig_name).suffix.lower()
    letter = "a"
    while (target_dir / f"{base}-{letter}{ext}").exists():
        letter = chr(ord(letter) + 1)
    return f"{base}-{letter}{ext}"


_EXIF_FIELDS = [
    "-FileName",
    "-FileSize",
    "-DateTimeOriginal",
    "-SubSecTimeOriginal",
    "-Model",
    "-SerialNumber",
    "-LensID",
    "-ExposureTime",
    "-FNumber",
    "-ISO",
    "-ExposureCompensation",
    "-FocalLength",
    "-WhiteBalance",
]


def extract_exif(files: List[Path]) -> List[Dict]:
    """Run exiftool -csv on files and return parsed rows — see README.md § ppsp_photos.csv."""
    cmd = ["exiftool", "-csv", "-f"] + _EXIF_FIELDS + [str(f) for f in files]
    result = run_command(cmd, "exiftool EXIF extraction", check=True)
    if not result or not result.stdout:
        return []
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def write_photos_csv(rows: List[Dict], csv_path: Path) -> None:
    """Write ppsp_photos.csv as tab-separated UTF-8 — see README.md § ppsp_photos.csv."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_photos_csv(csv_path: Path) -> List[Dict]:
    """Read a tab-separated ppsp_photos.csv and return rows as dicts — see README.md § ppsp_photos.csv."""
    with open(csv_path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return list(reader)
