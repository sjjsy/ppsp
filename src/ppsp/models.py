"""Data models for ppsp — see design.md § Data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional


class StackType(Enum):
    """HDR or focus-stack classification — see design.md § Stack."""

    HDR = "hdr"
    FOCUS = "focus"


@dataclass
class Photo:
    """Single image file after renaming — see design.md § Photo."""

    path: Path
    filename: str
    source_file: str
    timestamp: datetime
    model: str
    lens: str
    exposure_comp: float
    focal_length: float
    fnumber: float
    white_balance: str
    ext: str


@dataclass
class Stack:
    """Group of Photo objects belonging to the same scene — see design.md § Stack."""

    name: str
    path: Path
    photos: List[Photo]
    stack_type: StackType


@dataclass
class ChainSpec:
    """Parsed variant chain from a filename — see design.md § ChainSpec."""

    z_tier: str
    enfuse_id: str
    tmo_id: Optional[str]
    grading_id: str
    ct_id: Optional[str] = None


# Pattern: YYYYMMDDHHMMSS-CCCxxx-NNNN-<chain>.<ext>
# chain = z-tier + enfuse-id + optional-tmo-id + grading-id + optional-ct-id + optional q/r segments
_KNOWN_TMOS = {
    "m08d", "m08n", "m08c", "m08m",
    "m06d", "m06p", "m06b", "m06s",
    "drad", "dras", "drab", "dran",
    "r02d", "r02p", "r02h", "r02m",
    "fatd", "fatn", "fatc", "fats",
    "ferr", "ferw",
    "kimd", "kimn", "kiml", "kimv",
}
_KNOWN_CTS = {"ctw4", "ctw5", "ctd6", "ctc7", "ctc9"}


def parse_chain(filename: str, tmo_ids: Optional[List[str]] = None, ct_ids: Optional[List[str]] = None) -> Optional[ChainSpec]:
    """Parse a variant chain string from a filename — see README.md § Naming scheme.

    Returns None if the filename has no chain (i.e. it is an original camera file).
    """
    stem = Path(filename).stem
    # Original files have a single letter as chain component (a, b, c, ...)
    parts = stem.split("-")
    if len(parts) < 5:
        return None

    # The chain starts after YYYYMMDDHHMMSS-CCCxxx-NNNN
    chain_parts = parts[3:]
    if not chain_parts:
        return None

    # Single letter → original file
    if len(chain_parts) == 1 and re.fullmatch(r"[a-z]", chain_parts[0]):
        return None

    # Optional title shorthand sits between NNNN and the z-tier in named stacks.
    # Skip it so the rest of the parse proceeds normally.
    if chain_parts[0] not in ("z100", "z25", "z6", "z2") and len(chain_parts) > 1:
        chain_parts = chain_parts[1:]

    z_tier = chain_parts[0]
    if z_tier not in ("z100", "z25", "z6", "z2"):
        return None

    if len(chain_parts) < 3:
        return None

    enfuse_id = chain_parts[1]

    known_tmos = set(tmo_ids) if tmo_ids else _KNOWN_TMOS
    known_cts = set(ct_ids) if ct_ids else _KNOWN_CTS

    # Determine if there is a TMO id
    if len(chain_parts) >= 4 and chain_parts[2] in known_tmos:
        tmo_id: Optional[str] = chain_parts[2]
        grading_part_idx = 3
    else:
        tmo_id = None
        grading_part_idx = 2

    if grading_part_idx >= len(chain_parts):
        return None

    grading_raw = chain_parts[grading_part_idx]
    if grading_raw == "web":
        return None
    grading_id = grading_raw

    # Parse optional trailing segments: ct, q<int>, r<int> (in any order)
    ct_id: Optional[str] = None
    for part in chain_parts[grading_part_idx + 1:]:
        if part in known_cts:
            ct_id = part
        # q<int> and r<int> segments are recorded in the filename but not stored in ChainSpec;
        # they affect only the export step and are resolved from the filename at generate time.

    return ChainSpec(
        z_tier=z_tier,
        enfuse_id=enfuse_id,
        tmo_id=tmo_id,
        grading_id=grading_id,
        ct_id=ct_id,
    )


def compose_chain(spec: ChainSpec) -> str:
    """Compose a variant chain string from a ChainSpec — see README.md § Naming scheme."""
    parts = [spec.z_tier, spec.enfuse_id]
    if spec.tmo_id:
        parts.append(spec.tmo_id)
    parts.append(spec.grading_id)
    if spec.ct_id:
        parts.append(spec.ct_id)
    return "-".join(parts)
