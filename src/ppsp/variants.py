"""Variant parameter tables for enfuse, TMO, grading, and CT — see README.md § Variant system."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .models import ChainSpec


Z_TIERS: Tuple[str, ...] = ("z100", "z25", "z6", "z2")

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

# Luminance HDR v2.6.0 tone-mapping operator presets.
# Input TIFF is passed as a positional arg with -e 0; tuned variants use --tmoXxx flags.
# Within each operator group the defaults variant (d-suffix, no extra flags) is listed first,
# followed by tuned variants whose suffix hints at the emphasis vs. the default.
TMO_VARIANTS: Dict[str, List[str]] = {
    # --- Mantiuk ‘08 ---
    # --tmoM08ColorSaturation: post-mapping colour vibrancy (1.0 = neutral, 1.2–1.3 typical).
    # --tmoM08ConstrastEnh: contrast enhancement multiplier; note intentional typo in the binary.
    "m08d": ["--tmo", "mantiuk08"],                                              # Luminance defaults
    "m08n": ["--tmo", "mantiuk08",                                               # Natural / balanced; bright editorial look
             "--tmoM08ColorSaturation", "1.2",
             "--tmoM08ConstrastEnh", "2.0",
             "--gamma", "1.2",
             "--saturation", "1.2",
             "--postgamma", "1.1"],
    "m08c": ["--tmo", "mantiuk08",                                               # Contrast / punch; higher contrast same brightness
             "--tmoM08ColorSaturation", "1.3",
             "--tmoM08ConstrastEnh", "3.0",
             "--gamma", "1.2",
             "--postgamma", "1.1"],
    "m08m": ["--tmo", "mantiuk08",                                               # Moody / restrained; low enhancement, slightly dark
             "--tmoM08ColorSaturation", "1.1",
             "--tmoM08ConstrastEnh", "1.5",
             "--gamma", "1.0",
             "--postgamma", "0.95"],
    # --- Mantiuk ‘06 ---
    "m06d": ["--tmo", "mantiuk06"],                                              # Luminance defaults
    "m06p": ["--tmo", "mantiuk06",                                               # Punch / pop; strong micro-contrast
             "--tmoM06Contrast", "0.7",
             "--tmoM06Saturation", "1.4",
             "--tmoM06Detail", "1.0",
             "--gamma", "1.2",
             "--postgamma", "1.1"],
    "m06b": ["--tmo", "mantiuk06",                                               # Balanced; gentler than m06p, good general alternative
             "--tmoM06Contrast", "0.5",
             "--tmoM06Saturation", "1.2",
             "--tmoM06Detail", "0.8",
             "--gamma", "1.1",
             "--postgamma", "1.05"],
    "m06s": ["--tmo", "mantiuk06",                                               # Subtle / soft; minimal operator signature, clean lift
             "--tmoM06Contrast", "0.3",
             "--tmoM06Saturation", "1.0",
             "--tmoM06Detail", "0.6",
             "--gamma", "1.15",
             "--postgamma", "1.1"],
    # --- Drago ---
    "drad": ["--tmo", "drago"],                                                  # Luminance defaults
    "dras": ["--tmo", "drago",                                                   # Soft highlight roll-off; bright shadows
             "--tmoDrgBias", "0.85",
             "--postgamma", "1.1"],
    "drab": ["--tmo", "drago",                                                   # Higher bias; maximum shadow detail recovery
             "--tmoDrgBias", "0.95",
             "--postgamma", "1.05"],
    "dran": ["--tmo", "drago",                                                   # Neutral bias; lets highlights breathe, lower-key result
             "--tmoDrgBias", "0.75",
             "--postgamma", "1.0"],
    # --- Reinhard ‘02 ---
    "r02d": ["--tmo", "reinhard02"],                                             # Luminance defaults
    "r02p": ["--tmo", "reinhard02",                                              # Photographic / clean; zone-system key, brightened
             "--tmoR02Key", "0.18",
             "--tmoR02Phi", "1.0",
             "--postgamma", "1.1"],
    "r02h": ["--tmo", "reinhard02",                                              # High-key / bright; elevated midtone exposure
             "--tmoR02Key", "0.28",
             "--tmoR02Phi", "1.0",
             "--postgamma", "1.15"],
    "r02m": ["--tmo", "reinhard02",                                              # Moody / dark; low key, naturally shadowy atmosphere
             "--tmoR02Key", "0.10",
             "--tmoR02Phi", "1.0",
             "--postgamma", "1.0"],
    # --- Fattal ---
    "fatd": ["--tmo", "fattal"],                                                 # Luminance defaults
    "fatn": ["--tmo", "fattal",                                                  # Tamed / natural; desaturated, modestly lifted
             "--tmoFatColor", "0.8",
             "--gamma", "1.05",
             "--postgamma", "1.05"],
    "fatc": ["--tmo", "fattal",                                                  # Creative / dramatic; full gradient pop, subtle lift
             "--tmoFatAlpha", "0.8",
             "--tmoFatBeta", "0.9",
             "--postgamma", "1.05"],
    "fats": ["--tmo", "fattal",                                                  # Soft / low-gradient; reduced local contrast for plain walls
             "--tmoFatColor", "0.6",
             "--tmoFatAlpha", "0.5",
             "--tmoFatBeta", "0.95",
             "--gamma", "1.1",
             "--postgamma", "1.1"],
    # --- Ferradans and Ferwerda (no tuned variants) ---
    "ferr": ["--tmo", "ferradans"],
    "ferw": ["--tmo", "ferwerda"],
    # --- KimKautz ---
    # c1 = local contrast enhancement scale; c2 = global contrast / brightness balance.
    # Yields a clean, high-end magazine look — excellent for bright luxury interiors.
    "kimd": ["--tmo", "kimkautz"],                                               # Luminance defaults
    "kimn": ["--tmo", "kimkautz",                                                # Natural / luxury; clean magazine look
             "--tmoKimKautzC1", "0.8",
             "--tmoKimKautzC2", "1.2",
             "--postgamma", "1.1"],
    "kiml": ["--tmo", "kimkautz",                                                # Low contrast / dark; restrained and atmospheric
             "--tmoKimKautzC1", "0.5",
             "--tmoKimKautzC2", "0.9",
             "--postgamma", "1.0"],
    "kimv": ["--tmo", "kimkautz",                                                # Vibrant / punchy; enhanced local and global contrast
             "--tmoKimKautzC1", "1.0",
             "--tmoKimKautzC2", "1.5",
             "--postgamma", "1.15"],
}

GRADING_PRESETS: Dict[str, List[str]] = {
    "neut": [
        "-colorspace", "sRGB",
        "-unsharp", "0x0.8+0.5+0.05",
    ],
    "brig": [
        "-colorspace", "sRGB",
        "-sigmoidal-contrast", "3,50%",
        "-evaluate", "multiply", "1.10",
        "-modulate", "100,105,100",
        "-unsharp", "0x1+0.5+0.05",
    ],
    "deno": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "3,50%",
        "-evaluate", "multiply", "1.03",
        "-modulate", "100,105,100",
        "-unsharp", "0x1.5+1.0+0.05",
    ],
    "dens": [                                                                   # deno + saturation pulled down; counters oversaturated TMOs
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "3,50%",
        "-evaluate", "multiply", "1.03",
        "-modulate", "100,88,100",
        "-unsharp", "0x1.5+1.0+0.05",
    ],
    "dvi1": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "3,50%",
        "-evaluate", "multiply", "1.06",
        "-modulate", "100,112,100",
        "-unsharp", "0x1+0.8+0.05",
    ],
    "dvi2": [
        "-colorspace", "sRGB",
        "-despeckle",
        "-sigmoidal-contrast", "4,45%",
        "-evaluate", "multiply", "1.10",
        "-modulate", "100,118,100",
        "-unsharp", "0x1.2+0.6+0.05",
    ],
}

# Color-temperature presets — see README.md § Color-temperature presets
# Args are prepended before grading args (after a single -colorspace sRGB):
# the correct order is CT (channel gamma / white-point shift) before contrast/sharpening.
CT_PRESETS: Dict[str, List[str]] = {
    "ctw4": [
        "+level-colors", "black,#fff8e8",
        "-channel", "R", "-gamma", "1.10",
        "-channel", "G", "-gamma", "1.00",
        "-channel", "B", "-gamma", "0.90", "+channel",
    ],
    "ctw5": [
        "+level-colors", "black,#fffef5",
        "-channel", "R", "-gamma", "1.07",
        "-channel", "G", "-gamma", "1.02",
        "-channel", "B", "-gamma", "0.95", "+channel",
    ],
    "ctd6": [
        "+level-colors", "black,#fffffe",
    ],
    "ctc7": [
        "+level-colors", "black,#f5f8ff",
        "-channel", "R", "-gamma", "0.95",
        "-channel", "G", "-gamma", "0.97",
        "-channel", "B", "-gamma", "1.06", "+channel",
    ],
    "ctc9": [
        "+level-colors", "black,#f0f4ff",
        "-channel", "R", "-gamma", "0.92",
        "-channel", "G", "-gamma", "0.95",
        "-channel", "B", "-gamma", "1.12", "+channel",
    ],
    "ctr1": [                                                                   # reduce red — counter red-tinted TMOs (e.g. bathroom photos)
        "-channel", "R", "-gamma", "0.90",
        "-channel", "G", "-gamma", "1.03",
        "-channel", "B", "-gamma", "1.05", "+channel",
    ],
    "ctg1": [                                                                   # reduce green — counter green-tinted TMOs (e.g. rooms with green carpet)
        "-channel", "R", "-gamma", "1.02",
        "-channel", "G", "-gamma", "0.90",
        "-channel", "B", "-gamma", "1.02", "+channel",
    ],
}

# Preset level definitions: (enfuse_ids, tmo_ids, grading_ids, ct_ids) — see README.md § Variant levels
# ct_ids = [] means no CT variants; non-empty ct_ids generate additional chains on top of the base set.
VARIANT_LEVELS: Dict[str, Tuple[List[str], List[str], List[str], List[str]]] = {
    "some": (
        ["sel4"],
        ["m08n", "fatn"],
        ["neut", "dvi1"],
        [],
    ),
    "many": (
        ["natu", "sel4"],
        ["m08n", "r02p", "fatn"],
        ["neut", "dvi1"],
        ["ctw5"],
    ),
    "tmod": (
        ["sel4"],
        list(k for k in TMO_VARIANTS.keys() if k.endswith('d')),
        ["neut"],
        ["ctw5"],
    ),
    "lots": (
        ["natu", "sel3", "sel4", "sel6", "cont"],
        ["m08n", "m08c", "m06p", "r02p", "dras", "fatn", "fatc", "kimn"],
        ["neut", "brig", "dvi1", "dvi2"],
        ["ctw5"],
    ),
    "all": (
        list(ENFUSE_VARIANTS.keys()),
        list(TMO_VARIANTS.keys()),
        list(GRADING_PRESETS.keys()),
        list(CT_PRESETS.keys()),
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
    The z-tier must be one of z100, z25, z6, or z2.
    """
    parts = s.strip().split("-", 1)
    if len(parts) != 2:
        return None
    z_tier = parts[0]
    if z_tier not in Z_TIERS:
        return None
    spec = parse_variant_chain(parts[1])
    if spec is None:
        return None
    from .models import ChainSpec as _ChainSpec
    return _ChainSpec(z_tier=z_tier, enfuse_id=spec.enfuse_id, tmo_id=spec.tmo_id, grading_id=spec.grading_id, ct_id=spec.ct_id)


def parse_variant_chain(s: str) -> Optional[ChainSpec]:
    """Parse a compact chain spec like 'sel4-m08n-dvi1' or 'sel4-dvi1-ctw5' into a ChainSpec.

    Accepted lengths (segments separated by '-'):
      2: enfuse-grading
      3: enfuse-tmo-grading  OR  enfuse-grading-ct
      4: enfuse-tmo-grading-ct

    The z_tier is omitted and must be supplied by the caller at processing time.
    Returns None if the string cannot be resolved to a valid chain.
    """
    from .models import ChainSpec as _ChainSpec

    parts = s.strip().split("-")

    ct_id: Optional[str] = None
    tmo_id: Optional[str] = None

    if len(parts) == 2:
        enfuse_id, grading_id = parts
    elif len(parts) == 3:
        # Either enfuse-tmo-grading or enfuse-grading-ct
        if parts[1] in TMO_VARIANTS:
            enfuse_id, tmo_id, grading_id = parts
        elif parts[2] in CT_PRESETS:
            enfuse_id, grading_id = parts[0], parts[1]
            ct_id = parts[2]
        else:
            enfuse_id, tmo_id, grading_id = parts  # will fail validation below
    elif len(parts) == 4:
        enfuse_id, tmo_id, grading_id, ct_id = parts
    else:
        return None

    if enfuse_id not in ENFUSE_VARIANTS and enfuse_id != "focu":
        return None
    if tmo_id is not None and tmo_id not in TMO_VARIANTS:
        return None
    if grading_id not in GRADING_PRESETS:
        return None
    if ct_id is not None and ct_id not in CT_PRESETS:
        return None

    return _ChainSpec(z_tier="", enfuse_id=enfuse_id, tmo_id=tmo_id, grading_id=grading_id, ct_id=ct_id)


def expand_variants(level_or_list: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Expand a preset level or comma-separated ID list to (enfuse_ids, tmo_ids, grading_ids, ct_ids).

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
    ct_ids = [i for i in ids if i in CT_PRESETS]
    return enfuse_ids, tmo_ids, grading_ids, ct_ids


# ---------------------------------------------------------------------------
# Chain pattern expansion (regex / brace syntax) — see README.md § Pattern expansion
# ---------------------------------------------------------------------------


def _all_valid_variant_chains() -> List[str]:
    """Enumerate every valid variant chain string (enfuse + optional TMO + grading + optional CT, no z-tier)."""
    chains: List[str] = []
    enfuse_ids = list(ENFUSE_VARIANTS.keys()) + ["focu"]
    tmo_ids = list(TMO_VARIANTS.keys())
    grading_ids = list(GRADING_PRESETS.keys())
    ct_ids = list(CT_PRESETS.keys())
    for e in enfuse_ids:
        for g in grading_ids:
            chains.append(f"{e}-{g}")
            for ct in ct_ids:
                chains.append(f"{e}-{g}-{ct}")
        for t in tmo_ids:
            for g in grading_ids:
                chains.append(f"{e}-{t}-{g}")
                for ct in ct_ids:
                    chains.append(f"{e}-{t}-{g}-{ct}")
    return chains


def expand_variant_chain_pattern(pattern: str) -> List[str]:
    """Match a Python regex pattern against every valid variant chain (no z-tier component).

    Counterpart to ``expand_chain_pattern`` for use in the --discover path where chain specs
    are expressed without a z-tier prefix (e.g. ``sel4-m.*(p|n)-dvi1``).
    """
    try:
        results = [s for s in _all_valid_variant_chains() if re.fullmatch(pattern, s)]
    except re.error as exc:
        logging.warning("Invalid variant chain pattern '%s': %s", pattern, exc)
        return []
    if not results:
        logging.warning("Variant chain pattern '%s' matched no valid chains", pattern)
    return results


def _all_valid_chain_specs() -> List[str]:
    """Enumerate every valid full chain spec string (z-tier + enfuse + optional TMO + grading)."""
    specs: List[str] = []
    for z in Z_TIERS:
        for s in _all_valid_variant_chains():
            specs.append(f"{z}-{s}")
    return specs


def expand_chain_pattern(pattern: str) -> List[str]:
    """Match a Python regex pattern against every valid full chain spec string.

    The pattern is passed directly to ``re.fullmatch`` — use standard Python ``re``
    syntax.  Returns matching specs in canonical table order.
    Logs a warning and returns [] if nothing matches or the pattern is invalid.

    Examples::

        expand_chain_pattern("(z25|z100)-sel4-m06p-dvi1")
        # → ["z25-sel4-m06p-dvi1", "z100-sel4-m06p-dvi1"]

        expand_chain_pattern("z6-sel4-.*-dvi1")
        # → all z6/sel4/<any-tmo>/dvi1 specs  (16 entries, one per TMO variant)

        expand_chain_pattern("(z25|z100)-sel4-m.*(p|n)-dvi1")
        # → (z25|z100) × sel4 × {m06p,m08n} × dvi1  (4 entries)
    """
    try:
        results = [s for s in _all_valid_chain_specs() if re.fullmatch(pattern, s)]
    except re.error as exc:
        logging.warning("Invalid chain pattern '%s': %s", pattern, exc)
        return []
    if not results:
        logging.warning("Chain pattern '%s' matched no valid chain specs", pattern)
    return results
