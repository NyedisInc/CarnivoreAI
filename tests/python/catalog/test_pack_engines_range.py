
from __future__ import annotations

from typing import Any, Dict

import pytest

from src.core.catalog import plugin_pack
from src.core.catalog.engines_range import EngineRangeError, parse_range


def authored(**extra: Any) -> Dict[str, Any]:
    return {"id": "clock", "name": "clock", "version": "1.0.0", "author": "me", "sidecar": {"entry": "main.py"}, **extra}


@pytest.mark.parametrize("raw,lower", [
    (">=1.16.7", "1.16.7"), ("1.17", "1.17.0"), ("=1.16.6", "1.16.6"), ("^1.16.6", "1.16.6"), ("~1.16.6", "1.16.6"),
    (">=1.16.6 <2", "1.16.6"), ("1.16.6 - 1.18", "1.16.6"), ("^1.17 || >=1.16.6", "1.16.6"), (">=1.16.2 >=1.16.8", "1.16.8"),
    (">= 1.16.6", "1.16.6"), (">= 1.16.6 < 2", "1.16.6"),
])
def test_lower_bound_is_read(raw: str, lower: str) -> None:
    assert parse_range(raw).lower_text == lower


@pytest.mark.parametrize("raw", ["<2", "<=1.17", "*", "", "1.x", ">1.16.6", ">=1.16.6-beta", "foo", ">=01.16", "1.16.6 ||", ">=", 7, "> = 1.16.6", "> 1.16.6"])
def test_unusable_range_is_refused(raw: Any) -> None:
    with pytest.raises(EngineRangeError):
        parse_range(raw)


def test_lower_bound_becomes_min_app_version_and_engines_is_never_emitted() -> None:
    packed = plugin_pack.pack_manifest(authored(engines={"carnivore": ">=1.16.7"}))
    assert packed.carnivore["min_app_version"] == "1.16.7"
    assert "engines" not in packed.carnivore and "engines" not in packed.cplug
    assert any("engines.carnivore" in n for n in packed.notes)


def test_higher_existing_minimum_wins() -> None:
    assert plugin_pack.pack_manifest(authored(min_app_version="1.16.7", engines={"carnivore": ">=1.16.2"})).carnivore["min_app_version"] == "1.16.7"
    paged = authored(engines={"carnivore": ">=1.16.3"}, topics=["changed"])
    assert plugin_pack.pack_manifest(paged).carnivore["min_app_version"] == plugin_pack.PAGE_TOPICS_FLOOR


def test_upper_bound_is_noted() -> None:
    packed = plugin_pack.pack_manifest(authored(engines={"carnivore": ">=1.16.6 <2"}))
    assert any("upper bound" in n for n in packed.notes)


@pytest.mark.parametrize("engines", [{"carnivore": "<2"}, {"carnivore": ">1.16.6"}, {"carnivore": "nope"}, {"node": ">=18"}, ">=1.16.6"])
def test_pack_refuses_a_bad_engines_value(engines: Any) -> None:
    with pytest.raises(plugin_pack.PackError):
        plugin_pack.pack_manifest(authored(engines=engines))


def test_hand_written_pair_may_not_carry_engines() -> None:
    packed = plugin_pack.pack_manifest(authored())
    with pytest.raises(plugin_pack.PackError):
        plugin_pack.check_pair({**packed.carnivore, "engines": {"carnivore": ">=1.16.6"}}, packed.cplug)


@pytest.mark.parametrize("raw", ["=1.16.6", "1.16.6", ">= 1.16.6 <2"])
def test_exact_pin_is_noted_as_an_upper_bound(raw: str) -> None:
    packed = plugin_pack.pack_manifest(authored(engines={"carnivore": raw}))
    assert packed.carnivore["min_app_version"] == "1.16.6"
    assert any("upper bound" in n for n in packed.notes)


def test_open_minimum_has_no_upper_bound_note() -> None:
    for raw in (">=1.16.6", ">= 1.16.6"):
        assert not parse_range(raw).has_upper
