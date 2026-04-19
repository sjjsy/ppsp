"""Stack boundary detection and classification — see README.md § Step 2."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import Photo, Stack, StackType
from .rename import parse_timestamp


def photos_from_csv_rows(rows: List[Dict], source_dir: Path) -> List[Photo]:
    """Convert CSV dicts from ppsp_photos.csv to sorted Photo objects — see DESIGN.md § Photo."""
    photos: List[Photo] = []
    for row in rows:
        filename = row.get("FileName", "").strip()
        if not filename:
            continue
        ts = parse_timestamp(
            row.get("DateTimeOriginal", ""),
            row.get("SubSecTimeOriginal", ""),
        )
        if ts is None:
            ts = datetime.min

        try:
            exp_comp = float(row.get("ExposureCompensation", "0") or "0")
        except ValueError:
            exp_comp = 0.0

        try:
            focal = float(re.sub(r"[^\d.]", "", row.get("FocalLength", "0") or "0") or "0")
        except ValueError:
            focal = 0.0

        try:
            fnumber = float(re.sub(r"[^\d.]", "", row.get("FNumber", "0") or "0") or "0")
        except ValueError:
            fnumber = 0.0

        photos.append(
            Photo(
                path=source_dir / filename,
                filename=filename,
                source_file=row.get("SourceFile", filename),
                timestamp=ts,
                model=row.get("Model", "").strip(),
                lens=row.get("LensID", row.get("SerialNumber", "")).strip(),
                exposure_comp=exp_comp,
                focal_length=focal,
                fnumber=fnumber,
                white_balance=row.get("WhiteBalance", "").strip(),
                ext=Path(filename).suffix.lower(),
            )
        )
    photos.sort(key=lambda p: p.timestamp)
    return photos


def detect_stack_boundaries(photos: List[Photo], gap: float = 30.0) -> List[List[Photo]]:
    """Split photos into stacks using all five boundary signals — see README.md § Stack detection."""
    if not photos:
        return []

    groups: List[List[Photo]] = []
    current: List[Photo] = [photos[0]]

    for prev, curr in zip(photos, photos[1:]):
        new_stack = False

        # Signal 1: time gap
        if (curr.timestamp - prev.timestamp).total_seconds() > gap:
            new_stack = True

        # Signal 2: EV returns to 0 after a non-zero sequence
        if not new_stack and abs(prev.exposure_comp) >= 0.01 and abs(curr.exposure_comp) < 0.01:
            new_stack = True

        # Signal 3: focal length change > 0.5 mm
        if not new_stack and abs(curr.focal_length - prev.focal_length) > 0.5:
            new_stack = True

        # Signal 4: f-number change > 0.1
        if not new_stack and abs(curr.fnumber - prev.fnumber) > 0.1:
            new_stack = True

        # Signal 5: white balance string differs
        if not new_stack and curr.white_balance != prev.white_balance:
            new_stack = True

        if new_stack:
            groups.append(current)
            current = [curr]
        else:
            current.append(curr)

    groups.append(current)
    return groups


def detect_stack_type(photos: List[Photo]) -> StackType:
    """More than one distinct rounded EV → HDR, otherwise FOCUS — see README.md § Stack detection."""
    distinct_evs = {round(p.exposure_comp) for p in photos}
    if len(distinct_evs) > 1:
        return StackType.HDR
    return StackType.FOCUS


def make_stack_name(first_photo: Photo) -> str:
    """Derive a stack folder name from the first photo — see README.md § Naming scheme."""
    stem = Path(first_photo.filename).stem
    # Strip the trailing collision letter (single lowercase alpha)
    stem = re.sub(r"-[a-z]$", "", stem)
    return f"{stem}-stack"
