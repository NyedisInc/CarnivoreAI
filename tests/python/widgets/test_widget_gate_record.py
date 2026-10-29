
from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from src.cplugs.sdk.widget_gate import GATE_SCHEMA, GateRefused, record_digest, refusal_reasons, refuse_unless_passing

RECORD: Dict[str, Any] = {"id": "demo.card", "hosts": ["home", "terminal", "drawer", "popout", "glance"], "sizes": ["small", "wide"],
                          "fixtures": ["data", "empty"]}


def passing(**over: Any) -> Dict[str, Any]:
    gate = {"schema": GATE_SCHEMA, "widget": "demo.card", "record_sha256": record_digest(RECORD), "ok": True, "determined": True,
            "themes": ["carnivore", "acid_trip"], "hosts": list(RECORD["hosts"]), "sizes": ["small", "wide"], "fixtures": ["data", "empty"],
            "draws": 80, "findings": 0, "errors": 0, "failures": []}
    gate.update(over)
    return gate


def test_a_complete_passing_gate_record_is_accepted() -> None:
    assert refusal_reasons(RECORD, passing()) == []
    refuse_unless_passing(RECORD, passing())


def test_a_widget_with_no_gate_record_is_refused() -> None:
    assert refusal_reasons(RECORD, None) == ["no gate record: run scripts/widgets/gate.py"]
    with pytest.raises(GateRefused) as err:
        refuse_unless_passing(RECORD, None)
    assert err.value.widget == "demo.card"


@pytest.mark.parametrize("over,needle", [
    ({"ok": False, "failures": ["home/small: overflow-x"]}, "did not pass"),
    ({"failures": ["x"]}, "gate failure"),
    ({"findings": 2}, "findings"),
    ({"errors": 1}, "errors"),
    ({"determined": False}, "could not determine"),
    ({"themes": ["carnivore"]}, "theme"),
    ({"hosts": ["home"]}, "host(s) never drawn"),
    ({"sizes": ["small"]}, "size(s) never drawn: wide"),
    ({"fixtures": ["data"]}, "fixture(s) never drawn: empty"),
    ({"widget": "other.card"}, "not 'demo.card'"),
    ({"schema": 2}, "schema"),
    ({"record_sha256": "0" * 64}, "changed after the gate ran"),
])
def test_a_failing_thin_or_stale_gate_record_is_refused(over: Dict[str, Any], needle: str) -> None:
    reasons = refusal_reasons(RECORD, passing(**over))
    assert any(needle in r for r in reasons), reasons
    with pytest.raises(GateRefused):
        refuse_unless_passing(RECORD, passing(**over))


def test_editing_the_contract_record_makes_the_gate_record_stale() -> None:
    edited = copy.deepcopy(RECORD)
    edited["sizes"] = ["small", "wide", "full"]
    assert record_digest(edited) != record_digest(RECORD)
    assert any("changed after" in r for r in refusal_reasons(edited, passing()))



def test_a_keys_slice_is_marked_partial_and_written_beside_not_over_the_full_record(tmp_path) -> None:
    from scripts.widgets.gate import _gate_record, gate_path

    record = {"id": "core.x", "hosts": [], "sizes": [], "fixtures": ["data", "empty"], "remembers": []}
    sliced = _gate_record(record, [], [], ["a", "b"], [], "named", ["core.x:1"])
    full = _gate_record(record, [], [], ["a", "b"], [], "named", None)
    assert sliced["partial"] is True and sliced["keys"] == ["core.x:1"]
    assert full["partial"] is False and full["keys"] is None
    assert gate_path(tmp_path, "core.x", ["core.x:1"]).name == "core.x.partial.json"
    assert gate_path(tmp_path, "core.x", None).name == "core.x.gate.json"



def test_run_options_are_frozen_and_the_capture_cli_never_turns_the_gate_switch_on() -> None:
    import dataclasses

    from scripts.widgets.capture import RunOptions, parse

    options = RunOptions.from_args(parse([]))
    assert options.defects is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.defects = True  # type: ignore[misc]
