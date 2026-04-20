"""Variant parameter tables for enfuse, TMO, and grading — see README.md § Variant system."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .models import ChainSpec


ENFUSE_VARIANTS: Dict[str, List[str]] = {
    "natu": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.2",
        "--contrast-weight=0.2",
    ],
    "cons": [
        "--exposure-weight=0.8",
        "--saturation-weight=0.2",
        "--contrast-weight=0.3",
    ],
    "sel1": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.4",
        "--exposure-width=0.9",
    ],
    "sel2": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.3",
        "--exposure-width=0.7",
        "--hard-mask",
    ],
    "sel3": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.5",
        "--exposure-width=0.5",
        "--hard-mask",
    ],
    "sel4": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.6",
        "--exposure-width=0.4",
        "--hard-mask",
    ],
    "sel5": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.8",
        "--exposure-width=0.3",
        "--hard-mask",
    ],
    "sel6": [
        "--exposure-weight=1.0",
        "--saturation-weight=0.1",
        "--contrast-weight=0.8",
        "--exposure-width=0.2",
        "--hard-mask",
    ],
    "cont": [
        "--exposure-weight=0.6",
        "--saturation-weight=0.1",
        "--contrast-weight=0.8",
        "--hard-mask",
    ],
}

TMO_VARIANTS: Dict[str, List[str]] = {
    "ma06": ["--tmo", "mantiuk06"],
    "ma08": ["--tmo", "mantiuk08"],
    "ferr": ["--tmo", "ferradans"],
    "fatt": ["--tmo", "fattal"],
    "ferw": ["--tmo", "ferwerda"],
}

GRADING_PRESETS: Dict[str, List[str]] = {
    "neut": [
        "-colorspace", "sRGB",
        "-unsharp", "0x0.8+0.5+0.05",
    ],
    "warm": [
        "-colorspace", "sRGB",
        "-modulate", "100,108,97",
        "-unsharp", "0x0.8+0.5+0.05",
    ],
    "brig": [
        "-colorspace", "sRGB",
        "-sigmoidal-contrast", "3,50%",
        "-brightness-contrast", "8x-5",
        "-modulate", "100,105,100",
        "-unsharp", "0x1+0.5+0.05",
    ],
    "deno": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "3,50%",
        "-brightness-contrast", "6x-4",
        "-modulate", "100,106,100",
        "-unsharp", "0x1.5+1.0+0.05",
    ],
    "dvi1": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "3,50%",
        "-brightness-contrast", "7x-5",
        "-modulate", "100,125,100",
        "-unsharp", "0x1+0.8+0.05",
    ],
    "dvi2": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "4,45%",
        "-brightness-contrast", "12x-8",
        "-modulate", "100,118,100",
        "-unsharp", "0x1.2+0.6+0.05",
    ],
}

# Preset level definitions: (enfuse_ids, tmo_ids, grading_ids) — see README.md § Variant levels
VARIANT_LEVELS: Dict[str, Tuple[List[str], List[str], List[str]]] = {
    "some": (
        ["natu", "sel3", "sel4"],
        ["ma06", "fatt", "ferw"],
        ["neut", "brig", "dvi1"],          # 3 most practically useful for RE/arch
    ),
    "many": (
        ["natu", "sel3", "sel4", "sel6", "cont"],
        ["ma06", "ma08", "fatt", "ferr", "ferw"],
        ["neut", "warm", "brig", "dvi1", "dvi2"],
    ),
    "all": (
        list(ENFUSE_VARIANTS.keys()),
        list(TMO_VARIANTS.keys()),
        list(GRADING_PRESETS.keys()),
    ),
}

# Focus-stack enfuse parameters — see README.md § Enfuse variants
ENFUSE_FOCUS: List[str] = [
    "--contrast-weight=1",
    "--saturation-weight=0",
    "--exposure-weight=0",
    "--hard-mask",
    "--contrast-window-size=9",
]


def parse_full_chain_spec(s: str) -> Optional[ChainSpec]:
    """Parse a chain spec that includes an explicit z-tier prefix: 'z25-sel4-ma06-dvi1'.

    Returns a ChainSpec with z_tier set, or None if invalid.
    The z-tier must be one of z100, z25, or z13.
    """
    parts = s.strip().split("-", 1)
    if len(parts) != 2:
        return None
    z_tier = parts[0]
    if z_tier not in ("z100", "z25", "z13"):
        return None
    spec = parse_variant_chain(parts[1])
    if spec is None:
        return None
    from .models import ChainSpec as _ChainSpec
    return _ChainSpec(z_tier=z_tier, enfuse_id=spec.enfuse_id, tmo_id=spec.tmo_id, grading_id=spec.grading_id)


def parse_variant_chain(s: str) -> Optional[ChainSpec]:
    """Parse a compact chain spec like 'sel4-fatt-dvi1' or 'sel4-neut' into a ChainSpec.

    The z_tier is omitted from the spec and must be supplied by the caller at processing time.
    Returns None if the string cannot be resolved to a valid (enfuse, optional-tmo, grading) chain.
    """
    from .models import ChainSpec as _ChainSpec

    parts = s.strip().split("-")
    if len(parts) == 2:
        enfuse_id, grading_id = parts
        tmo_id: Optional[str] = None
    elif len(parts) == 3:
        enfuse_id, tmo_id, grading_id = parts
    else:
        return None

    if enfuse_id not in ENFUSE_VARIANTS and enfuse_id != "focu":
        return None
    if tmo_id is not None and tmo_id not in TMO_VARIANTS:
        return None
    if grading_id not in GRADING_PRESETS:
        return None

    return _ChainSpec(z_tier="", enfuse_id=enfuse_id, tmo_id=tmo_id, grading_id=grading_id)


def expand_variants(level_or_list: str) -> Tuple[List[str], List[str], List[str]]:
    """Expand a preset level or comma-separated ID list to (enfuse_ids, tmo_ids, grading_ids).

    Tokens are classified by which dictionary they appear in; a single token may only belong
    to one class. Mode 3 (chain specs containing '-') is not handled here — see commands.py.

    See README.md § Variant levels for preset definitions.
    """
    if level_or_list in VARIANT_LEVELS:
        return VARIANT_LEVELS[level_or_list]

    ids = [x.strip() for x in level_or_list.split(",") if x.strip()]
    enfuse_ids = [i for i in ids if i in ENFUSE_VARIANTS]
    tmo_ids = [i for i in ids if i in TMO_VARIANTS]
    grading_ids = [i for i in ids if i in GRADING_PRESETS]
    return enfuse_ids, tmo_ids, grading_ids
