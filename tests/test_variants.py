"""Unit tests for variants.py — see DESIGN.md § Testing strategy."""

from __future__ import annotations

import pytest

from ppsp.variants import (
    ENFUSE_VARIANTS,
    GRADING_PRESETS,
    TMO_VARIANTS,
    VARIANT_LEVELS,
    expand_variants,
)


def test_expand_variants_some():
    enfuse_ids, tmo_ids = expand_variants("some")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4"}
    assert set(tmo_ids) == {"ma06", "fatt", "ferw"}


def test_expand_variants_many():
    enfuse_ids, tmo_ids = expand_variants("many")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4", "sel6", "cont"}
    assert set(tmo_ids) == {"ma06", "ma08", "fatt", "ferr", "ferw"}


def test_expand_variants_all():
    enfuse_ids, tmo_ids = expand_variants("all")
    assert set(enfuse_ids) == set(ENFUSE_VARIANTS.keys())
    assert set(tmo_ids) == set(TMO_VARIANTS.keys())


def test_expand_variants_custom_list():
    enfuse_ids, tmo_ids = expand_variants("natu,sel3,fatt,ma06")
    assert set(enfuse_ids) == {"natu", "sel3"}
    assert set(tmo_ids) == {"fatt", "ma06"}


def test_expand_variants_unknown_ignored():
    enfuse_ids, tmo_ids = expand_variants("natu,unknownXXX,fatt")
    assert "unknownXXX" not in enfuse_ids
    assert "unknownXXX" not in tmo_ids
    assert "natu" in enfuse_ids
    assert "fatt" in tmo_ids


def test_all_enfuse_ids_have_params():
    for eid, params in ENFUSE_VARIANTS.items():
        assert isinstance(params, list), f"{eid} params not a list"
        assert len(params) > 0, f"{eid} has empty params"


def test_all_tmo_ids_have_params():
    for tid, params in TMO_VARIANTS.items():
        assert isinstance(params, list), f"{tid} params not a list"
        assert len(params) > 0, f"{tid} has empty params"


def test_all_grading_ids_have_params():
    for gid, params in GRADING_PRESETS.items():
        assert isinstance(params, list), f"{gid} params not a list"
        assert len(params) > 0, f"{gid} has empty params"
