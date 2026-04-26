"""Stack naming: title assignment, shorthand generation, ppsp_stacks.csv management — see design.md § Naming."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .util import run_command

# Articles and conjunctions omitted when building the shorthand.
# Spatial prepositions (from, to, into, through, over, between…) are kept because
# they carry directional meaning in real-estate scene titles
# (e.g. "from the door to the window" → f…t…w).
_FILLER_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but",
})

# Matches both "-stack" suffix dirs and named dirs (YYYYMMDDHHMMSS-CCCxxx-NNNN-suffix).
_STACK_DIR_RE = re.compile(r"^\d{14}-[a-z0-9]{6}-\d{4}-.+$")

STACKS_CSV = "ppsp_stacks.csv"
_STACKS_CSV_FIELDS = ["StackFolder", "Title", "Shorthand", "Photos", "GenerateSpecs"]


def title_to_shorthand(title: str) -> str:
    """Return a filesystem-safe shorthand from a human title.

    Takes the first char of each significant word (omitting filler words), lowercase.
    E.g. "Bedroom B from the door to the window" → "bbfdtw"
    """
    words = re.split(r"[\s\-_]+", title.strip())
    chars = [w[0].lower() for w in words if w and w.lower() not in _FILLER_WORDS]
    if chars:
        return "".join(chars)
    # Fallback: strip non-alphanumeric and take first 6 chars
    return re.sub(r"[^a-z0-9]", "", title.lower())[:6] or "x"


def is_stack_dir(d: Path) -> bool:
    """Return True if d is a stack directory (either -stack suffix or named shorthand)."""
    return d.is_dir() and bool(_STACK_DIR_RE.match(d.name))


def find_stack_dirs(source: Path) -> List[Path]:
    """Return sorted list of all stack dirs directly under source."""
    return sorted(d for d in source.iterdir() if is_stack_dir(d))


def stack_dir_prefix(stack_dir_name: str) -> str:
    """Return the YYYYMMDDHHMMSS-CCCxxx-NNNN portion of a stack dir name."""
    return "-".join(stack_dir_name.split("-")[:3])


def stack_dir_to_filename_base(stack_dir_name: str) -> str:
    """Return the base prefix used in variant filenames for this stack dir.

    For -stack dirs: strip the '-stack' suffix.
    For named dirs: return the name as-is (includes the shorthand).
    """
    if stack_dir_name.endswith("-stack"):
        return stack_dir_name[: -len("-stack")]
    return stack_dir_name


def load_stacks_csv(source: Path) -> List[Dict]:
    """Read ppsp_stacks.csv and return rows as dicts."""
    csv_path = source / STACKS_CSV
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def save_stacks_csv(source: Path, rows: List[Dict]) -> None:
    """Write ppsp_stacks.csv as tab-separated UTF-8."""
    csv_path = source / STACKS_CSV
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=_STACKS_CSV_FIELDS, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def build_stacks_csv_rows(source: Path, existing: Optional[List[Dict]] = None) -> List[Dict]:
    """Scan source for stack dirs and build/update stacks CSV rows.

    Preserves existing Title, Shorthand, and GenerateSpecs values from prior rows.
    """
    existing_by_folder: Dict[str, Dict] = {}
    if existing:
        for row in existing:
            existing_by_folder[row.get("StackFolder", "")] = row

    rows: List[Dict] = []
    for stack_dir in find_stack_dirs(source):
        folder_name = stack_dir.name
        prev = existing_by_folder.get(folder_name, {})

        photo_count = sum(
            1 for f in stack_dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".arw", ".jpg", ".jpeg", ".tif", ".tiff")
        )

        title = prev.get("Title", "")
        shorthand = title_to_shorthand(title) if title else ""
        rows.append({
            "StackFolder": folder_name,
            "Title": title,
            "Shorthand": shorthand,
            "Photos": str(photo_count),
            "GenerateSpecs": prev.get("GenerateSpecs", ""),
        })

    return rows


def write_title_metadata(path: Path, title: str) -> None:
    """Write title to image EXIF/XMP/IPTC metadata via exiftool."""
    run_command(
        [
            "exiftool", "-overwrite_original",
            f"-Title={title}",
            f"-XMP:Title={title}",
            f"-IPTC:ObjectName={title}",
            f"-EXIF:ImageDescription={title}",
            str(path),
        ],
        "write title metadata",
        check=False,
    )


def rename_stack(stack_dir: Path, title: str, source: Path) -> Optional[Path]:
    """Rename stack folder and contained files to embed the title shorthand.

    Old: YYYYMMDDHHMMSS-CCCxxx-NNNN-stack/  and files like base-chain.jpg
    New: YYYYMMDDHHMMSS-CCCxxx-NNNN-{shorthand}/  and files like base-{shorthand}-chain.jpg

    Returns the new stack dir path, or None on failure.
    """
    shorthand = title_to_shorthand(title)
    base = stack_dir_prefix(stack_dir.name)
    new_name = f"{base}-{shorthand}"
    new_dir = source / new_name

    if new_dir == stack_dir:
        return stack_dir

    if new_dir.exists():
        logging.warning("Target stack dir already exists: %s", new_dir)
        return None

    old_file_prefix = f"{base}-"
    new_file_prefix = f"{base}-{shorthand}-"

    def _rename_files_in(directory: Path) -> None:
        for f in sorted(directory.iterdir()):
            if f.is_dir():
                _rename_files_in(f)
            elif f.is_file() and f.name.startswith(old_file_prefix):
                tail = f.name[len(old_file_prefix):]
                # Skip if shorthand is already present to avoid double-insertion on redo.
                if not tail.startswith(f"{shorthand}-") and tail != shorthand:
                    f.rename(directory / (new_file_prefix + tail))

    _rename_files_in(stack_dir)
    stack_dir.rename(new_dir)
    logging.info("Renamed stack: %s → %s", stack_dir.name, new_name)
    return new_dir


def write_metadata_to_stack(stack_dir: Path, title: str) -> None:
    """Write title metadata to all image files in the stack dir (recursively)."""
    for f in stack_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".arw", ".jpg", ".jpeg", ".tif", ".tiff"):
            write_title_metadata(f, title)
