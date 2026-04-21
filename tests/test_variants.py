"""Unit tests for variants.py — see DESIGN.md § Testing strategy."""

from __future__ import annotations

import pytest

from ppsp.variants import (
    ENFUSE_VARIANTS,
    GRADING_PRESETS,
    TMO_VARIANTS,
    VARIANT_LEVELS,
    expand_variants,
    parse_full_chain_spec,
    parse_variant_chain,
)


def test_expand_variants_some():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("some")
    assert set(enfuse_ids) == {"sel4"}
    assert set(tmo_ids) == {"m08n", "fatn"}
    assert set(grading_ids) == {"neut", "dvi1"}


def test_expand_variants_many():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("many")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4"}
    assert set(tmo_ids) == {"m08n", "fatn"}
    assert set(grading_ids) == {"neut", "dvi1"}


def test_expand_variants_lots():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("lots")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4", "sel6", "cont"}
    assert set(tmo_ids) == {"m08n", "m08c", "m06p", "r02p", "dras", "fatc"}
    assert len(grading_ids) == 5
    assert "deno" not in grading_ids


def test_expand_variants_all():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("all")
    assert set(enfuse_ids) == set(ENFUSE_VARIANTS.keys())
    assert set(tmo_ids) == set(TMO_VARIANTS.keys())
    assert set(grading_ids) == set(GRADING_PRESETS.keys())
    # KimKautz must be present in the all level
    assert "kimd" in tmo_ids
    assert "kimn" in tmo_ids


def test_expand_variants_custom_list_with_grading():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("natu,sel3,fatc,m06p,dvi1")
    assert set(enfuse_ids) == {"natu", "sel3"}
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert set(grading_ids) == {"dvi1"}


def test_expand_variants_custom_list_no_grading():
    """When no grading IDs are given, grading_ids is empty — callers fall back to all presets."""
    enfuse_ids, tmo_ids, grading_ids = expand_variants("natu,sel3,fatc,m06p")
    assert set(enfuse_ids) == {"natu", "sel3"}
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert grading_ids == []


def test_expand_variants_unknown_ignored():
    enfuse_ids, tmo_ids, grading_ids = expand_variants("natu,unknownXXX,fatc")
    assert "unknownXXX" not in enfuse_ids
    assert "unknownXXX" not in tmo_ids
    assert "unknownXXX" not in grading_ids
    assert "natu" in enfuse_ids
    assert "fatc" in tmo_ids


def test_expand_variants_single_grading_two_variants():
    """sel3,fatc,m06p,dvi1 → enfuse:[sel3] tmo:[fatc,m06p] grading:[dvi1] → 2 TMO variants."""
    enfuse_ids, tmo_ids, grading_ids = expand_variants("sel3,fatc,m06p,dvi1")
    assert enfuse_ids == ["sel3"]
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert grading_ids == ["dvi1"]
    # 1 enfuse × 2 TMO × 1 grading = 2 TMO variants, plus 1 enfuse-only variant


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


# ---------------------------------------------------------------------------
# parse_variant_chain
# ---------------------------------------------------------------------------


def test_parse_chain_with_tmo():
    spec = parse_variant_chain("sel4-fatc-dvi1")
    assert spec is not None
    assert spec.enfuse_id == "sel4"
    assert spec.tmo_id == "fatc"
    assert spec.grading_id == "dvi1"
    assert spec.z_tier == ""


def test_parse_chain_without_tmo():
    spec = parse_variant_chain("sel4-neut")
    assert spec is not None
    assert spec.enfuse_id == "sel4"
    assert spec.tmo_id is None
    assert spec.grading_id == "neut"


def test_parse_chain_natu_m06p_warm():
    spec = parse_variant_chain("natu-m06p-warm")
    assert spec is not None
    assert spec.enfuse_id == "natu"
    assert spec.tmo_id == "m06p"
    assert spec.grading_id == "warm"


def test_parse_chain_focu_focus_stack():
    spec = parse_variant_chain("focu-neut")
    assert spec is not None
    assert spec.enfuse_id == "focu"
    assert spec.tmo_id is None
    assert spec.grading_id == "neut"


def test_parse_chain_invalid_enfuse_id():
    assert parse_variant_chain("badid-fatc-dvi1") is None


def test_parse_chain_invalid_tmo_id():
    assert parse_variant_chain("sel4-badtmo-dvi1") is None


def test_parse_chain_invalid_grading_id():
    assert parse_variant_chain("sel4-fatc-badgrading") is None


def test_parse_chain_too_short():
    assert parse_variant_chain("sel4") is None


def test_parse_chain_too_many_parts():
    assert parse_variant_chain("sel4-fatc-dvi1-extra") is None


def test_parse_chain_user_example():
    """The three chains from the feature request all parse correctly."""
    specs = [
        parse_variant_chain("sel4-fatc-dvi1"),
        parse_variant_chain("sel4-fatc-neut"),
        parse_variant_chain("sel4-m06p-dvi1"),
    ]
    assert all(s is not None for s in specs)
    assert specs[0].tmo_id == "fatc" and specs[0].grading_id == "dvi1"
    assert specs[1].tmo_id == "fatc" and specs[1].grading_id == "neut"
    assert specs[2].tmo_id == "m06p" and specs[2].grading_id == "dvi1"


# ---------------------------------------------------------------------------
# parse_full_chain_spec
# ---------------------------------------------------------------------------


def test_parse_full_chain_spec_with_tmo():
    spec = parse_full_chain_spec("z25-sel4-m06p-dvi1")
    assert spec is not None
    assert spec.z_tier == "z25"
    assert spec.enfuse_id == "sel4"
    assert spec.tmo_id == "m06p"
    assert spec.grading_id == "dvi1"


def test_parse_full_chain_spec_without_tmo():
    spec = parse_full_chain_spec("z100-sel4-neut")
    assert spec is not None
    assert spec.z_tier == "z100"
    assert spec.enfuse_id == "sel4"
    assert spec.tmo_id is None
    assert spec.grading_id == "neut"


def test_parse_full_chain_spec_z6():
    spec = parse_full_chain_spec("z6-natu-fatc-brig")
    assert spec is not None
    assert spec.z_tier == "z6"
    assert spec.enfuse_id == "natu"
    assert spec.tmo_id == "fatc"
    assert spec.grading_id == "brig"


def test_parse_full_chain_spec_focu():
    spec = parse_full_chain_spec("z25-focu-neut")
    assert spec is not None
    assert spec.z_tier == "z25"
    assert spec.enfuse_id == "focu"
    assert spec.tmo_id is None
    assert spec.grading_id == "neut"


def test_parse_full_chain_spec_invalid_ztier():
    assert parse_full_chain_spec("z99-sel4-m06p-dvi1") is None


def test_parse_full_chain_spec_z13_now_invalid():
    assert parse_full_chain_spec("z13-natu-fatc-brig") is None


def test_parse_full_chain_spec_no_ztier():
    assert parse_full_chain_spec("sel4-m06p-dvi1") is None


def test_parse_full_chain_spec_invalid_chain():
    assert parse_full_chain_spec("z25-badid-m06p-dvi1") is None


def test_parse_full_chain_spec_too_short():
    assert parse_full_chain_spec("z25-sel4") is None
