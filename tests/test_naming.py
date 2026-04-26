"""Unit tests for naming.py — title_to_shorthand, rename_stack, stacks CSV."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ppsp.naming import (
    build_stacks_csv_rows,
    find_stack_dirs,
    is_stack_dir,
    load_stacks_csv,
    rename_stack,
    save_stacks_csv,
    stack_dir_to_filename_base,
    stack_dir_prefix,
    title_to_shorthand,
)


# ---------------------------------------------------------------------------
# title_to_shorthand
# ---------------------------------------------------------------------------


def test_shorthand_basic():
    assert title_to_shorthand("Bedroom B from the door to the window") == "bbfdtw"


def test_shorthand_filters_articles_and_conjunctions():
    # "the", "and" are filtered; "kitchen", "living", "room" kept
    assert title_to_shorthand("the kitchen and the living room") == "klr"


def test_shorthand_lowercases():
    assert title_to_shorthand("Master Bedroom North Wall") == "mbnw"


def test_shorthand_single_word():
    assert title_to_shorthand("Hallway") == "h"


def test_shorthand_all_filler_fallback():
    # All filler → falls back to first 6 lowercase alphanum chars
    result = title_to_shorthand("the a an")
    assert result  # non-empty
    assert result.isalpha()


def test_shorthand_hyphenated_words():
    # Hyphens treated as word separators
    result = title_to_shorthand("Open-Plan Living")
    assert "o" in result
    assert "p" in result
    assert "l" in result


# ---------------------------------------------------------------------------
# is_stack_dir / find_stack_dirs
# ---------------------------------------------------------------------------


def test_is_stack_dir_old_style(tmp_path):
    d = tmp_path / "20260415115544-m4aens-2441-stack"
    d.mkdir()
    assert is_stack_dir(d)


def test_is_stack_dir_named(tmp_path):
    d = tmp_path / "20260415115544-m4aens-2441-bbfdtw"
    d.mkdir()
    assert is_stack_dir(d)


def test_is_stack_dir_false_for_other_dirs(tmp_path):
    for name in ("cull", "variants", "out-1920", "z25"):
        d = tmp_path / name
        d.mkdir()
        assert not is_stack_dir(d)


def test_find_stack_dirs_mixed(tmp_path):
    (tmp_path / "20260415115544-m4aens-2441-stack").mkdir()
    (tmp_path / "20260415115544-m4aens-2442-bbfdtw").mkdir()
    (tmp_path / "cull").mkdir()
    dirs = find_stack_dirs(tmp_path)
    assert len(dirs) == 2
    assert all(is_stack_dir(d) for d in dirs)


# ---------------------------------------------------------------------------
# stack_dir_to_filename_base
# ---------------------------------------------------------------------------


def test_filename_base_old_style():
    assert stack_dir_to_filename_base("20260415115544-m4aens-2441-stack") == \
        "20260415115544-m4aens-2441"


def test_filename_base_named():
    assert stack_dir_to_filename_base("20260415115544-m4aens-2441-bbfdtw") == \
        "20260415115544-m4aens-2441-bbfdtw"


# ---------------------------------------------------------------------------
# stack_dir_prefix
# ---------------------------------------------------------------------------


def test_stack_dir_prefix():
    assert stack_dir_prefix("20260415115544-m4aens-2441-stack") == \
        "20260415115544-m4aens-2441"
    assert stack_dir_prefix("20260415115544-m4aens-2441-bbfdtw") == \
        "20260415115544-m4aens-2441"


# ---------------------------------------------------------------------------
# rename_stack
# ---------------------------------------------------------------------------


def test_rename_stack_creates_new_dir(tmp_path):
    stack_dir = tmp_path / "20260415115544-m4aens-2441-stack"
    stack_dir.mkdir()
    (stack_dir / "20260415115544-m4aens-2441-a.arw").touch()
    (stack_dir / "20260415115544-m4aens-2441-b.arw").touch()

    new_dir = rename_stack(stack_dir, "Bedroom B from the door to the window", tmp_path)
    assert new_dir is not None
    assert new_dir.name == "20260415115544-m4aens-2441-bbfdtw"
    assert new_dir.exists()
    assert not stack_dir.exists()


def test_rename_stack_renames_files(tmp_path):
    stack_dir = tmp_path / "20260415115544-m4aens-2441-stack"
    stack_dir.mkdir()
    (stack_dir / "20260415115544-m4aens-2441-a.arw").touch()
    z_dir = stack_dir / "z25"
    z_dir.mkdir()
    (z_dir / "20260415115544-m4aens-2441-z25-sel4-dvi1.jpg").touch()

    new_dir = rename_stack(stack_dir, "Master Bedroom North Wall", tmp_path)
    assert new_dir is not None
    shorthand = "mbnw"
    assert (new_dir / f"20260415115544-m4aens-2441-{shorthand}-a.arw").exists()
    assert (new_dir / "z25" / f"20260415115544-m4aens-2441-{shorthand}-z25-sel4-dvi1.jpg").exists()


def test_rename_stack_noop_if_already_named(tmp_path):
    shorthand = "mbnw"
    stack_dir = tmp_path / f"20260415115544-m4aens-2441-{shorthand}"
    stack_dir.mkdir()

    result = rename_stack(stack_dir, "Master Bedroom North Wall", tmp_path)
    assert result == stack_dir


def test_rename_stack_fails_if_target_exists(tmp_path):
    stack_dir = tmp_path / "20260415115544-m4aens-2441-stack"
    stack_dir.mkdir()
    conflict = tmp_path / "20260415115544-m4aens-2441-mbnw"
    conflict.mkdir()

    result = rename_stack(stack_dir, "Master Bedroom North Wall", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# ppsp_stacks.csv round-trip
# ---------------------------------------------------------------------------


def test_stacks_csv_round_trip(tmp_path):
    rows = [
        {
            "StackFolder": "20260415115544-m4aens-2441-stack",
            "Title": "Bedroom",
            "Shorthand": "b",
            "Photos": "3",
            "GenerateSpecs": "z25-sel4-dvi1",
        }
    ]
    save_stacks_csv(tmp_path, rows)
    loaded = load_stacks_csv(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["Title"] == "Bedroom"
    assert loaded[0]["GenerateSpecs"] == "z25-sel4-dvi1"


def test_build_stacks_csv_rows(tmp_path):
    d1 = tmp_path / "20260415115544-m4aens-2441-stack"
    d1.mkdir()
    (d1 / "20260415115544-m4aens-2441-a.arw").touch()
    (d1 / "20260415115544-m4aens-2441-b.jpg").touch()

    rows = build_stacks_csv_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["StackFolder"] == d1.name
    assert rows[0]["Photos"] == "2"
    assert rows[0]["Title"] == ""


def test_build_stacks_csv_rows_preserves_title(tmp_path):
    d1 = tmp_path / "20260415115544-m4aens-2441-stack"
    d1.mkdir()

    existing = [{"StackFolder": d1.name, "Title": "Bedroom", "Shorthand": "b",
                 "Photos": "0", "GenerateSpecs": "z25-sel4-dvi1"}]
    rows = build_stacks_csv_rows(tmp_path, existing)
    assert rows[0]["Title"] == "Bedroom"
    assert rows[0]["GenerateSpecs"] == "z25-sel4-dvi1"
