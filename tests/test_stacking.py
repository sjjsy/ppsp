"""Unit tests for stacking.py — see design.md § Testing strategy."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ppsp.models import Photo, StackType
from ppsp.stacking import (
    detect_stack_boundaries,
    detect_stack_type,
    make_stack_name,
)

_BASE_TS = datetime(2026, 4, 16, 9, 55, 0)


def make_photo(
    timestamp_offset_sec: float,
    ev: float = 0.0,
    focal: float = 50.0,
    fnumber: float = 8.0,
    wb: str = "Daylight",
    filename: str = "",
) -> Photo:
    """Factory for synthetic Photo objects in tests."""
    ts = _BASE_TS + timedelta(seconds=timestamp_offset_sec)
    fname = filename or f"20260416095500-rm4zzz-0001-a.arw"
    return Photo(
        path=Path(fname),
        filename=fname,
        source_file=fname,
        timestamp=ts,
        model="ILCE-7RM4",
        lens="SEL1635GM",
        exposure_comp=ev,
        focal_length=focal,
        fnumber=fnumber,
        white_balance=wb,
        ext=".arw",
    )


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------


def test_single_photo_makes_one_stack():
    photos = [make_photo(0)]
    groups = detect_stack_boundaries(photos)
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_time_gap_splits_stack():
    photos = [make_photo(0), make_photo(5), make_photo(60)]
    groups = detect_stack_boundaries(photos, gap=30.0)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 1


def test_ev_return_to_zero_splits():
    # Sequence: 0, -2, +2, 0 — the final 0 after non-zero triggers a new stack
    photos = [
        make_photo(0, ev=0.0),
        make_photo(2, ev=-2.0),
        make_photo(4, ev=2.0),
        make_photo(6, ev=0.0),
    ]
    groups = detect_stack_boundaries(photos, gap=30.0)
    assert len(groups) == 2
    assert len(groups[0]) == 3
    assert len(groups[1]) == 1


def test_focal_length_change_splits():
    photos = [make_photo(0, focal=35.0), make_photo(2, focal=35.0), make_photo(4, focal=50.0)]
    groups = detect_stack_boundaries(photos, gap=300.0)
    assert len(groups) == 2


def test_fnumber_change_splits():
    photos = [make_photo(0, fnumber=8.0), make_photo(2, fnumber=8.0), make_photo(4, fnumber=11.0)]
    groups = detect_stack_boundaries(photos, gap=300.0)
    assert len(groups) == 2


def test_white_balance_change_splits():
    photos = [
        make_photo(0, wb="Daylight"),
        make_photo(2, wb="Daylight"),
        make_photo(4, wb="Tungsten"),
    ]
    groups = detect_stack_boundaries(photos, gap=300.0)
    assert len(groups) == 2


# ---------------------------------------------------------------------------
# Stack type detection
# ---------------------------------------------------------------------------


def test_hdr_type_detection():
    photos = [make_photo(0, ev=0), make_photo(2, ev=-2), make_photo(4, ev=2)]
    assert detect_stack_type(photos) == StackType.HDR


def test_focus_type_detection():
    photos = [make_photo(0, ev=0), make_photo(2, ev=0), make_photo(4, ev=0)]
    assert detect_stack_type(photos) == StackType.FOCUS


# ---------------------------------------------------------------------------
# Stack name
# ---------------------------------------------------------------------------


def test_make_stack_name():
    photo = make_photo(0, filename="20260416095500-rm4zzz-2126-a.arw")
    name = make_stack_name(photo)
    assert name == "20260416095500-rm4zzz-2126-stack"
    assert not name.endswith("-a-stack")
