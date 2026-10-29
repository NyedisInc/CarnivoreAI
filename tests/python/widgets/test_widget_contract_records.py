
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.cplugs.sdk.sidecar import validate_document
from src.cplugs.sdk.widget_decl import problems_in

DATA = Path(__file__).resolve().parents[3] / "src" / "data"
RECORDS: List[Dict[str, Any]] = json.loads((DATA / "widget-contracts.json").read_text(encoding="utf-8"))["widgets"]
REGISTRY: List[str] = [row["id"] for row in json.loads((DATA / "widgets.json").read_text(encoding="utf-8"))["widgets"]]


def third_party(**over: Any) -> Dict[str, Any]:
    base = copy.deepcopy(next(r for r in RECORDS if r["id"] == "core.notes"))
    base.update({"id": "acme/clock", "tier": "catalog", "source": "catalog", "declarative": True, "license": "MIT",
                 "permissions": [], "reads": [{"kind": "feed", "ref": "clock.tick"}]})
    base.update(over)
    return base


def test_there_are_records_and_a_registry_to_compare() -> None:
    assert len(REGISTRY) > 14 and len(RECORDS) == len(REGISTRY)


def test_every_registered_widget_has_a_record_and_every_record_a_registered_widget() -> None:
    ids = [r["id"] for r in RECORDS]
    assert [i for i in REGISTRY if i not in ids] == [], "registered widgets with no contract record"
    assert [i for i in ids if i not in REGISTRY] == [], "contract records for widgets the registry lacks"
    assert ids == REGISTRY, "records follow registry order"
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("record", RECORDS, ids=[r["id"] for r in RECORDS])
def test_every_record_validates(record: Dict[str, Any]) -> None:
    assert validate_document(record) == []
    assert problems_in(record) == []
    assert record["tier"] == "builtin" and record["source"] == "builtin" and record["declarative"] is False


def test_the_registry_comparison_goes_red() -> None:
    ids = [r["id"] for r in RECORDS]
    assert ids[1:] != REGISTRY
    assert [*ids, "core.ghost"] != REGISTRY


def test_a_valid_third_party_declarative_widget_passes() -> None:
    assert validate_document(third_party()) == []


@pytest.mark.parametrize("over,needle", [
    ({"declarative": False}, "declarative"),
    ({"source": "sideload"}, "source"),
    ({"tier": "builtin"}, "source"),
    ({"reads": []}, "reads"),
    ({"fixtures": ["data"]}, "fixtures"),
    ({"script": "x.js"}, "script"),
])
def test_the_schema_refuses_a_code_running_or_undeclared_third_party_widget(over: Dict[str, Any], needle: str) -> None:
    errors = validate_document(third_party(**over))
    assert errors and any(needle in e for e in errors), errors


def test_cross_field_rules_catch_what_the_schema_cannot() -> None:
    rec = copy.deepcopy(RECORDS[0])
    assert problems_in({**rec, "hosts": ["home", "popout", "glance"]})
    assert problems_in({**rec, "hosts": ["terminal", "popout"]})
    assert problems_in({**rec, "max_per_surface": 3})
    assert problems_in({**rec, "glance": {"height": 40}})


def test_remembers_validates_and_a_bad_name_is_refused() -> None:
    ok = copy.deepcopy(RECORDS[0])
    ok["remembers"] = []
    assert validate_document(ok) == []
    ok["remembers"] = ["status-folds"]
    assert validate_document(ok) == []
    ok["remembers"] = ["Not Flat"]
    assert validate_document(ok) != []
