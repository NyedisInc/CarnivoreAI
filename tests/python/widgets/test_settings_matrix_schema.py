
from __future__ import annotations

import copy

import pytest

from src.core.item_settings_schema import SettingsSchemaError, parse_schema

GOOD = {
    "version": 1,
    "fields": {
        "aOff": {"kind": "boolean", "labelKey": "x.row.a", "default": True},
        "aOn": {"kind": "boolean", "labelKey": "x.row.a", "default": True},
        "n": {"kind": "number", "labelKey": "x.n", "default": 1},
    },
    "groups": [
        {"labelKey": "x.group", "fields": ["aOff", "aOn"], "matrix": {
            "columns": ["x.col.off", "x.col.on"],
            "rows": [{"labelKey": "x.row.a", "hintKey": "x.row.a_help", "fields": ["aOff", "aOn"]}, {"labelKey": "x.row.never", "locked": True}]}},
        {"labelKey": "x.other", "fields": ["n"]},
    ],
}


def test_a_good_matrix_parses_and_rides_the_wire() -> None:
    wire = parse_schema(copy.deepcopy(GOOD)).as_wire()
    assert wire["groups"][0]["matrix"] == GOOD["groups"][0]["matrix"]
    assert "matrix" not in wire["groups"][1]


def test_a_row_may_ask_before_a_cell_is_ticked_and_the_ask_rides_the_wire() -> None:
    schema = copy.deepcopy(GOOD)
    schema["groups"][0]["matrix"]["rows"][0]["confirm"] = {"aOff": "x.row.a_confirm"}
    wire = parse_schema(schema).as_wire()
    assert wire["groups"][0]["matrix"]["rows"][0]["confirm"] == {"aOff": "x.row.a_confirm"}


def test_beast_mode_asks_before_each_beast_off_auto_approve_box() -> None:
    from src.core.approvals import beast_grid

    asks = {beast_grid.row_for(row_id).cell(beast_grid.MODE_OFF) for row_id in beast_grid.UNCONFIRMED_ROWS}
    assert asks == {"claudePermissionOff", "codexApprovalOff", "agentWritesOff"}


def _break(mutate):
    schema = copy.deepcopy(GOOD)
    mutate(schema["groups"][0]["matrix"], schema)
    return schema


@pytest.mark.parametrize("mutate", [
    lambda m, s: m.update(columns=["x.col.off"]),
    lambda m, s: m.update(columns=["x.col.off", "Not A Key"]),
    lambda m, s: m["rows"][0].update(fields=["aOff"]),
    lambda m, s: m["rows"][0].update(fields=["aOn", "aOff"]),
    lambda m, s: m["rows"][1].update(fields=["aOff", "aOn"]),
    lambda m, s: m["rows"][1].update(locked=False),
    lambda m, s: m["rows"].pop(0),
    lambda m, s: m.update(extra=1),
    lambda m, s: m["rows"][0].update(fields=["aOff", "n"]),
    lambda m, s: m["rows"][0].update(confirm={"n": "x.confirm"}),
    lambda m, s: m["rows"][0].update(confirm={"aOff": "Not A Key"}),
    lambda m, s: m["rows"][0].update(confirm={}),
    lambda m, s: m["rows"][1].update(confirm={"aOff": "x.confirm"}),
    lambda m, s: (s["groups"][0]["fields"].append("n"), s["groups"].pop(1),
                  m["rows"][0].update(fields=["aOff", "n"]), m["rows"].insert(1, {"labelKey": "x.r", "fields": ["aOn", "aOn"]})),
], ids=["one_column", "bad_column_key", "short", "order", "locked_with_cells", "locked_false", "unnamed", "extra_key",
        "outside_group", "confirm_outside_row", "confirm_bad_key", "confirm_empty", "confirm_on_locked", "not_boolean"])
def test_a_malformed_matrix_is_refused(mutate) -> None:
    with pytest.raises(SettingsSchemaError):
        parse_schema(_break(mutate))
