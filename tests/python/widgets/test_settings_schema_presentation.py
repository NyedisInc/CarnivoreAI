from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.item_settings_schema import SettingsSchemaError, parse_schema

WIDGETS_JSON = Path(__file__).resolve().parents[3] / "src" / "data" / "widgets.json"


def _declared(widget_id: str) -> dict:
    rows = json.loads(WIDGETS_JSON.read_text(encoding="utf-8"))["widgets"]
    return next(row["settings"] for row in rows if row["id"] == widget_id)


def test_the_activity_log_schema_round_trips_with_its_group_and_hint():
    raw = _declared("core.activity-log")
    assert raw["groups"] and raw["fields"]["showSystem"]["hintKey"]
    assert parse_schema(raw).as_wire() == raw


def test_a_field_may_carry_keywords_the_settings_search_matches():
    raw = {"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "keywordsKey": "x.a_words", "default": True}}}
    assert parse_schema(raw).as_wire() == raw


def test_a_schema_without_groups_answers_none():
    raw = {"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True}}}
    assert parse_schema(raw).as_wire() == raw


@pytest.mark.parametrize("raw, words", [
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True}},
      "groups": [{"labelKey": "x.g", "fields": []}]}, "fields must list declared fields"),
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True},
                               "b": {"kind": "boolean", "labelKey": "x.b", "default": True}},
      "groups": [{"labelKey": "x.g", "fields": ["a"]}]}, "every field exactly once"),
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True}},
      "groups": [{"labelKey": "x.g", "fields": ["a"]}, {"labelKey": "x.h", "fields": ["a"]}]}, "every field exactly once"),
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True, "hintKey": "Not A Key"}}},
     "hintKey must be a catalog key"),
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True, "keywordsKey": "Not A Key"}}},
     "keywordsKey must be a catalog key"),
    ({"version": 1, "fields": {"a": {"kind": "boolean", "labelKey": "x.a", "default": True, "control": "select"}}},
     "unknown field: control"),
    ({"version": 1, "fields": {"a": {"kind": "enum", "labelKey": "x.a", "default": "p", "options": ["p"], "control": "dial"}}},
     "not segmented or select"),
])
def test_each_malformed_presentation_is_refused_by_name(raw, words):
    with pytest.raises(SettingsSchemaError, match=words):
        parse_schema(raw)
