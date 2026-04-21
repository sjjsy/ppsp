"""Unit tests for parse_chain / compose_chain round-trips — see DESIGN.md § ChainSpec."""

from __future__ import annotations

import pytest

from ppsp.models import ChainSpec, compose_chain, parse_chain


def test_compose_chain_with_tmo():
    spec = ChainSpec(z_tier="z25", enfuse_id="sel3", tmo_id="fatc", grading_id="dvi2", web=False)
    assert compose_chain(spec) == "z25-sel3-fatc-dvi2"


def test_compose_chain_no_tmo():
    spec = ChainSpec(z_tier="z100", enfuse_id="natu", tmo_id=None, grading_id="neut", web=False)
    assert compose_chain(spec) == "z100-natu-neut"


def test_compose_chain_web():
    spec = ChainSpec(z_tier="z100", enfuse_id="sel4", tmo_id="m06p", grading_id="warm", web=True)
    assert compose_chain(spec) == "z100-sel4-m06p-warm-web"


def test_parse_chain_with_tmo():
    filename = "20260416095559-m4azzz-2126-z25-sel3-fatc-dvi2.jpg"
    spec = parse_chain(filename)
    assert spec is not None
    assert spec.z_tier == "z25"
    assert spec.enfuse_id == "sel3"
    assert spec.tmo_id == "fatc"
    assert spec.grading_id == "dvi2"
    assert spec.web is False


def test_parse_chain_no_tmo():
    filename = "20260416095559-m4azzz-2126-z100-natu-neut.jpg"
    spec = parse_chain(filename)
    assert spec is not None
    assert spec.z_tier == "z100"
    assert spec.enfuse_id == "natu"
    assert spec.tmo_id is None
    assert spec.grading_id == "neut"
    assert spec.web is False


def test_parse_chain_web():
    filename = "20260416095559-m4azzz-2126-z100-sel4-m06p-warm-web.jpg"
    spec = parse_chain(filename)
    assert spec is not None
    assert spec.tmo_id == "m06p"
    assert spec.grading_id == "warm"
    assert spec.web is True


def test_parse_chain_original_returns_none():
    filename = "20260416095559-m4azzz-2126-a.arw"
    assert parse_chain(filename) is None


def test_roundtrip_compose_parse():
    spec = ChainSpec(z_tier="z6", enfuse_id="cont", tmo_id="ferw", grading_id="brig", web=False)
    chain = compose_chain(spec)
    filename = f"20260416095559-m4azzz-2126-{chain}.jpg"
    parsed = parse_chain(filename)
    assert parsed is not None
    assert parsed.z_tier == spec.z_tier
    assert parsed.enfuse_id == spec.enfuse_id
    assert parsed.tmo_id == spec.tmo_id
    assert parsed.grading_id == spec.grading_id
    assert parsed.web == spec.web
