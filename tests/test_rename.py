"""Unit tests for rename.py — see DESIGN.md § Testing strategy."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from ppsp.rename import compute_refined_name, parse_timestamp


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------


def test_parse_timestamp_valid():
    dt = parse_timestamp("2026:04:16 09:55:59")
    assert dt == datetime(2026, 4, 16, 9, 55, 59)


def test_parse_timestamp_with_subsec():
    dt = parse_timestamp("2026:04:16 09:55:59", subsec="123")
    assert dt is not None
    assert dt.year == 2026
    assert dt.microsecond == 123000


def test_parse_timestamp_invalid_returns_none():
    assert parse_timestamp("not-a-date") is None
    assert parse_timestamp("") is None
    assert parse_timestamp("-") is None


# ---------------------------------------------------------------------------
# compute_refined_name
# ---------------------------------------------------------------------------


def test_compute_refined_name_basic():
    ts = datetime(2026, 4, 16, 9, 55, 59)
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir)
        name = compute_refined_name(ts, "ILCE-7RM4", "SEL1635GM", "DSC02126.ARW", target)
    # CCC = last 3 chars of model = "rm4", LLL = last 3 chars of lens = "5gm"
    # Format: YYYYMMDDHHMMSS-CCCxxx-NNNN-letter.ext  (CCC+LLL run together, no hyphen between them)
    assert name.startswith("20260416095559-")
    assert "-rm45gm-" in name
    assert "-2126-" in name
    assert name.endswith("-a.arw")


def test_compute_refined_name_zzz_fallback():
    ts = datetime(2026, 1, 1, 0, 0, 0)
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir)
        name = compute_refined_name(ts, "", "", "IMG_0001.jpg", target)
    assert "-zzz" in name
    assert "zzz-" in name


def test_compute_refined_name_collision_suffix():
    ts = datetime(2026, 4, 16, 9, 55, 59)
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir)
        # Pre-create the 'a' collision
        first = compute_refined_name(ts, "ILCE-7RM4", "SEL1635GM", "DSC02126.ARW", target)
        (target / first).touch()
        second = compute_refined_name(ts, "ILCE-7RM4", "SEL1635GM", "DSC02126.ARW", target)
    assert first.endswith("-a.arw")
    assert second.endswith("-b.arw")
    assert first[:-6] == second[:-6]  # same base, different letter


def test_compute_refined_name_no_digits_in_orig():
    ts = datetime(2026, 1, 1, 12, 0, 0)
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir)
        name = compute_refined_name(ts, "ILCE-7RM4", "SEL1635GM", "photo.jpg", target)
    assert "-0000-" in name
