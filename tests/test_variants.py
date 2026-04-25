"""Unit tests for variants.py — see DESIGN.md § Testing strategy."""

from __future__ import annotations

import pytest

from ppsp.variants import (
    CT_PRESETS,
    ENFUSE_VARIANTS,
    GRADING_PRESETS,
    TMO_VARIANTS,
    VARIANT_LEVELS,
    expand_chain_pattern,
    expand_variants,
    parse_full_chain_spec,
    parse_variant_chain,
)


def test_expand_variants_some():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("some")
    assert set(enfuse_ids) == {"sel4"}
    assert set(tmo_ids) == {"m08n", "fatn"}
    assert set(grading_ids) == {"neut", "dvi1"}
    assert ct_ids == []


def test_expand_variants_many():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("many")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4"}
    assert set(tmo_ids) == {"m08n", "fatn"}
    assert set(grading_ids) == {"neut", "dvi1"}
    assert ct_ids == ["ctw5"]


def test_expand_variants_lots():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("lots")
    assert set(enfuse_ids) == {"natu", "sel3", "sel4", "sel6", "cont"}
    assert set(tmo_ids) == {"m08n", "m08c", "m06p", "r02p", "dras", "fatc"}
    assert len(grading_ids) == 4
    assert "deno" not in grading_ids
    assert "warm" not in grading_ids
    assert "dv1w" not in grading_ids
    assert ct_ids == ["ctw5"]


def test_expand_variants_all():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("all")
    assert set(enfuse_ids) == set(ENFUSE_VARIANTS.keys())
    assert set(tmo_ids) == set(TMO_VARIANTS.keys())
    assert set(grading_ids) == set(GRADING_PRESETS.keys())
    assert set(ct_ids) == set(CT_PRESETS.keys())
    # KimKautz must be present in the all level
    assert "kimd" in tmo_ids
    assert "kimn" in tmo_ids


def test_expand_variants_custom_list_with_grading():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("natu,sel3,fatc,m06p,dvi1")
    assert set(enfuse_ids) == {"natu", "sel3"}
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert set(grading_ids) == {"dvi1"}
    assert ct_ids == []


def test_expand_variants_custom_list_no_grading():
    """When no grading IDs are given, grading_ids is empty — callers fall back to all presets."""
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("natu,sel3,fatc,m06p")
    assert set(enfuse_ids) == {"natu", "sel3"}
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert grading_ids == []
    assert ct_ids == []


def test_expand_variants_unknown_ignored():
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("natu,unknownXXX,fatc")
    assert "unknownXXX" not in enfuse_ids
    assert "unknownXXX" not in tmo_ids
    assert "unknownXXX" not in grading_ids
    assert "natu" in enfuse_ids
    assert "fatc" in tmo_ids


def test_expand_variants_single_grading_two_variants():
    """sel3,fatc,m06p,dvi1 → enfuse:[sel3] tmo:[fatc,m06p] grading:[dvi1] → 2 TMO variants."""
    enfuse_ids, tmo_ids, grading_ids, ct_ids = expand_variants("sel3,fatc,m06p,dvi1")
    assert enfuse_ids == ["sel3"]
    assert set(tmo_ids) == {"fatc", "m06p"}
    assert grading_ids == ["dvi1"]
    assert ct_ids == []
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


def test_parse_chain_natu_m06p_dvi1():
    spec = parse_variant_chain("natu-m06p-dvi1")
    assert spec is not None
    assert spec.enfuse_id == "natu"
    assert spec.tmo_id == "m06p"
    assert spec.grading_id == "dvi1"
    assert spec.ct_id is None


def test_parse_chain_with_ct():
    spec = parse_variant_chain("sel4-m08n-dvi1-ctw5")
    assert spec is not None
    assert spec.enfuse_id == "sel4"
    assert spec.tmo_id == "m08n"
    assert spec.grading_id == "dvi1"
    assert spec.ct_id == "ctw5"


def test_parse_chain_warm_invalid():
    """warm is no longer a grading preset — should return None."""
    assert parse_variant_chain("natu-m06p-warm") is None


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


# ---------------------------------------------------------------------------
# expand_chain_pattern
# ---------------------------------------------------------------------------


def test_expand_chain_pattern_literal_spec():
    """A plain (no-meta) spec resolves to exactly that one spec."""
    result = expand_chain_pattern("z25-sel4-m06p-dvi1")
    assert result == ["z25-sel4-m06p-dvi1"]


def test_expand_chain_pattern_ztier_alternation():
    """(z25|z100)-sel4-m06p-dvi1 → exactly those two specs."""
    result = expand_chain_pattern("(z25|z100)-sel4-m06p-dvi1")
    assert sorted(result) == ["z100-sel4-m06p-dvi1", "z25-sel4-m06p-dvi1"]


def test_expand_chain_pattern_tmo_wildcard():
    """z6-sel4-.*-dvi1 → all z6/sel4/<tmo>/dvi1 chains (one per TMO variant)."""
    result = expand_chain_pattern("z6-sel4-.*-dvi1")
    assert len(result) == len(TMO_VARIANTS)
    assert all(s.startswith("z6-sel4-") and s.endswith("-dvi1") for s in result)
    assert "z6-sel4-dvi1" not in result  # enfuse-only chain must not appear


def test_expand_chain_pattern_char_class():
    """(z25|z100)-sel4-m.*[pn]-dvi1 → z25/z100 × sel4 × {m06p,m08n} × dvi1."""
    result = expand_chain_pattern("(z25|z100)-sel4-m.*[pn]-dvi1")
    assert sorted(result) == [
        "z100-sel4-m06p-dvi1",
        "z100-sel4-m08n-dvi1",
        "z25-sel4-m06p-dvi1",
        "z25-sel4-m08n-dvi1",
    ]


def test_expand_chain_pattern_no_match_returns_empty(caplog):
    """A pattern matching nothing returns [] and emits a warning."""
    import logging
    with caplog.at_level(logging.WARNING):
        result = expand_chain_pattern("z25-badenfuse-m06p-dvi1")
    assert result == []
    assert "matched no valid chain specs" in caplog.text


def test_expand_chain_pattern_deduplicates():
    """Overlapping alternation must not produce duplicate specs."""
    result = expand_chain_pattern("(z25|z25)-sel4-m06p-dvi1")
    assert result.count("z25-sel4-m06p-dvi1") == 1


def test_expand_chain_pattern_enfuse_only():
    """Pattern without a TMO segment resolves to enfuse-only chains."""
    result = expand_chain_pattern("z25-sel4-dvi1")
    assert result == ["z25-sel4-dvi1"]


def test_expand_chain_pattern_all_gradings_wildcard():
    """z25-sel4-m06p-.* → sel4/m06p with every grading preset × (no CT + each CT)."""
    result = expand_chain_pattern("z25-sel4-m06p-.*")
    assert len(result) == len(GRADING_PRESETS) * (len(CT_PRESETS) + 1)
    assert all(s.startswith("z25-sel4-m06p-") for s in result)
