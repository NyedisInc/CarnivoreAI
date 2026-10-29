
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts.widgets import harness
from scripts.widgets.gate import gate_widget
from src.cplugs.sdk.widget_gate import GateRefused, refuse_unless_passing

RECORDS: Dict[str, Dict[str, Any]] = {
    r["id"]: r for r in json.loads((Path(harness.REPO) / "src" / "data" / "widget-contracts.json").read_text(encoding="utf-8"))["widgets"]
}


def published_and_themes(page: Any, base: str) -> tuple[List[dict], List[str]]:
    return harness.catalog(page, base)


def test_a_clean_widget_passes_and_its_gate_record_is_accepted(page_and_base) -> None:
    page, base = page_and_base
    published, themes = published_and_themes(page, base)
    record = RECORDS["core.keep-awake"]
    dark = [t for t in themes if t != "carnivore-light"][:2]
    gate = gate_widget(page, base, record, published, dark)
    assert gate["ok"] is True and gate["failures"] == [], gate["failures"][:3]
    assert gate["draws"] > 0 and len(gate["themes"]) == 2
    assert set(record["hosts"]) <= set(gate["hosts"]) and set(record["sizes"]) <= set(gate["sizes"])
    refuse_unless_passing(record, gate)


def test_the_gate_goes_red_on_a_broken_widget(page_and_base) -> None:
    page, base = page_and_base
    published, themes = published_and_themes(page, base)
    notes = next(w for w in published if w["key"] == "core.notes")
    probe = {**copy.deepcopy(notes), "key": "harness.fit-probe", "manifest": "harness.fit-probe", "fixture": True}
    record = {**copy.deepcopy(RECORDS["core.notes"]), "id": "harness.fit-probe", "hosts": ["home"]}
    gate = gate_widget(page, base, record, [probe], themes[:2])
    assert gate["ok"] is False and gate["findings"] > 0, gate
    assert any("overflow-x" in f for f in gate["failures"])
    with pytest.raises(GateRefused):
        refuse_unless_passing(record, gate)


def test_a_widget_with_no_fixture_fails_the_gate(page_and_base) -> None:
    page, base = page_and_base
    published, themes = published_and_themes(page, base)
    record = {**copy.deepcopy(RECORDS["core.shell"]), "fixtures": []}
    gate = gate_widget(page, base, record, published, themes[:2])
    assert gate["ok"] is False and gate["draws"] == 0
    assert any("fixture" in f for f in gate["failures"]), gate["failures"]


def test_one_theme_is_not_enough(page_and_base) -> None:
    page, base = page_and_base
    published, themes = published_and_themes(page, base)
    gate = gate_widget(page, base, RECORDS["core.keep-awake"], published, themes[:1])
    assert gate["ok"] is False and any("theme" in f for f in gate["failures"])
