"""Data models for ppsp — see DESIGN.md § Data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional


class StackType(Enum):
    """HDR or focus-stack classification — see DESIGN.md § Stack."""

    HDR = "hdr"
    FOCUS = "focus"


@dataclass
class Photo:
    """Single image file after renaming — see DESIGN.md § Photo."""

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
    """Group of Photo objects belonging to the same scene — see DESIGN.md § Stack."""

    name: str
    path: Path
    photos: List[Photo]
    stack_type: StackType


@dataclass
class ChainSpec:
    """Parsed variant chain from a filename — see DESIGN.md § ChainSpec."""

    z_tier: str
    enfuse_id: str
    tmo_id: Optional[str]
    grading_id: str
    web: bool = False


# Pattern: YYYYMMDDHHMMSS-CCCxxx-NNNN-<chain>.<ext>
# chain = z-tier + enfuse-id + optional-tmo-id + grading-id + optional -web
_CHAIN_RE = re.compile(
    r"^(?P<z>z(?:100|25|6))-(?P<enfuse>[a-z0-9]+)-(?P<rest>.+)$"
)

_KNOWN_TMOS = {"m08d", "m08n", "m08c", "m06d", "m06p", "drad", "dras", "r02d", "r02p", "fatd", "fatn", "fatc", "ferr", "ferw", "kimd", "kimn"}
_KNOWN_GRADINGS = {"neut", "warm", "brig", "deno", "dvi1", "dvi2"}


def parse_chain(filename: str, tmo_ids: Optional[List[str]] = None) -> Optional[ChainSpec]:
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

    z_tier = chain_parts[0]
    if z_tier not in ("z100", "z25", "z6", "z2"):
        return None

    if len(chain_parts) < 3:
        return None

    enfuse_id = chain_parts[1]

    known_tmos = set(tmo_ids) if tmo_ids else _KNOWN_TMOS

    # Determine if there is a TMO id
    if len(chain_parts) >= 4 and chain_parts[2] in known_tmos:
        tmo_id: Optional[str] = chain_parts[2]
        grading_part_idx = 3
    else:
        tmo_id = None
        grading_part_idx = 2

    if grading_part_idx >= len(chain_parts):
        return None

    web = False
    grading_raw = chain_parts[grading_part_idx]
    if grading_raw == "web":
        return None
    grading_id = grading_raw

    # Check for trailing -web
    if grading_part_idx + 1 < len(chain_parts) and chain_parts[grading_part_idx + 1] == "web":
        web = True

    return ChainSpec(
        z_tier=z_tier,
        enfuse_id=enfuse_id,
        tmo_id=tmo_id,
        grading_id=grading_id,
        web=web,
    )


def compose_chain(spec: ChainSpec) -> str:
    """Compose a variant chain string from a ChainSpec — see README.md § Naming scheme."""
    parts = [spec.z_tier, spec.enfuse_id]
    if spec.tmo_id:
        parts.append(spec.tmo_id)
    parts.append(spec.grading_id)
    if spec.web:
        parts.append("web")
    return "-".join(parts)
