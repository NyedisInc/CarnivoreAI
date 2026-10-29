
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.subagents import files, shape_alert
from tests.helpers.subagent_fixture import CONV, PROJECT_DIR, build_corpus
from src.core.subagents.contract import (
    SHAPE_OK,
    SHAPE_UNRECOGNIZED,
    check_line,
    check_meta,
)

@pytest.fixture()
def sub(tmp_path: Path) -> Path:
    build_corpus(tmp_path / "projects")
    return tmp_path / "projects" / PROJECT_DIR / CONV / "subagents"


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    shape_alert.reset_for_tests()
    yield
    files.reset_caches_for_tests()
    shape_alert.reset_for_tests()


def _first_line(sub: Path, name: str) -> dict:
    with open(sub / name, encoding="utf-8") as handle:
        return json.loads(handle.readline())


def test_every_well_formed_fixture_meta_passes(sub):
    metas = sorted(sub.glob("agent-*.meta.json"))
    assert metas, "the fixture directory is empty: this test would pass over nothing"
    outcomes = {p.name: check_meta(json.loads(p.read_text())).outcome for p in metas}
    bad = {name for name, outcome in outcomes.items() if outcome != SHAPE_OK}
    assert bad == {"agent-a7000000000000007.meta.json"}


def test_every_fixture_line_passes(sub):
    line = _first_line(sub, "agent-a1000000000000001.jsonl")
    assert check_line(line).outcome == SHAPE_OK


@pytest.mark.parametrize("key", ["type", "timestamp", "agentId", "isSidechain", "sessionId"])
def test_a_line_missing_a_required_key_is_named(sub, key):
    line = _first_line(sub, "agent-a1000000000000001.jsonl")
    del line[key]
    check = check_line(line)
    assert check.outcome == SHAPE_UNRECOGNIZED
    assert check.problems == (f"required key {key} absent",)


def test_a_meta_without_agent_type_is_named():
    check = check_meta({"description": "x", "toolUseId": "toolu_1"})
    assert check.outcome == SHAPE_UNRECOGNIZED


def test_a_known_optional_key_of_another_type_is_named_and_a_bool_is_not_an_int():
    assert check_meta({"agentType": "w", "spawnDepth": True}).outcome == SHAPE_UNRECOGNIZED
    assert check_meta({"agentType": "w", "spawnDepth": 2}).outcome == SHAPE_OK


def test_an_additive_meta_key_is_listed_and_still_recognised():
    check = check_meta({"agentType": "w", "brandNewKey": 1})
    assert check.outcome == SHAPE_OK and check.unknown_keys == ("brandNewKey",)


def test_a_non_object_document_is_named_not_raised():
    assert check_meta(["agentType"]).outcome == SHAPE_UNRECOGNIZED
    assert check_line("text").outcome == SHAPE_UNRECOGNIZED


def test_a_torn_final_line_is_not_a_shape_change(sub):
    target = sub / "agent-a9000000000000009.jsonl"
    assert not target.read_bytes().endswith(b"\n")
    assert files.read_line_facts(target).state == SHAPE_OK


def test_a_broken_line_file_is_named_on_read(sub):
    target = sub / "agent-a8000000000000008.jsonl"
    assert files.read_line_facts(target).state == SHAPE_UNRECOGNIZED


def test_a_meta_caught_mid_write_is_unreadable_not_unrecognised(tmp_path):
    target = tmp_path / "agent-a1.meta.json"
    target.write_text('{"agentType": "wor')
    assert files.read_meta_facts(target).state == files.FILE_UNREADABLE



_SECRET_VALUE = "VALUE-SENTINEL-must-never-reach-a-note"

_SECRET_INT = 7314159265358


def _broken_check():
    return check_meta({"agentType": _SECRET_INT, "description": _SECRET_VALUE,
                       "toolUseId": _SECRET_VALUE})


def test_the_note_is_written_only_when_the_switch_is_on(tmp_path):
    off = shape_alert.report_unrecognized(_broken_check(), enabled=lambda: False,
                                          debug_dir=tmp_path)
    assert off is False
    assert not (tmp_path / shape_alert.NOTE_FILENAME).exists()
    shape_alert.reset_for_tests()
    on = shape_alert.report_unrecognized(_broken_check(), claude_code_version="2.1.999",
                                         enabled=lambda: True, debug_dir=tmp_path)
    assert on is True
    note = (tmp_path / shape_alert.NOTE_FILENAME).read_text()
    assert "subagent_meta" in note and "agentType" in note and "2.1.999" in note


def test_the_note_holds_names_and_types_never_values(tmp_path):
    shape_alert.report_unrecognized(_broken_check(), enabled=lambda: True, debug_dir=tmp_path)
    note = (tmp_path / shape_alert.NOTE_FILENAME).read_text()
    assert "key agentType is integer" in note
    assert _SECRET_VALUE not in note
    assert str(_SECRET_INT) not in note


def test_one_signature_is_noted_once(tmp_path):
    for _ in range(3):
        shape_alert.report_unrecognized(_broken_check(), enabled=lambda: True,
                                        debug_dir=tmp_path)
    note = (tmp_path / shape_alert.NOTE_FILENAME).read_text()
    assert note.count("## Claude Code file shape changed") == 1


@pytest.mark.parametrize("kind", ["fork-context-ref", "api-request", "api-request-shape", "api-request-blob"])
def test_a_bookkeeping_line_without_the_turn_envelope_is_recognised(kind, monkeypatch):
    from src.core.subagents import contract

    line = {"type": kind, "agentId": "a1", "parentSessionId": "p1", "contextLength": 3}
    assert contract.check_line(line).recognized
    monkeypatch.setattr(contract, "LINE_BOOKKEEPING_KINDS", ())
    problems = contract.check_line(line).problems
    assert problems == ("required key timestamp absent", "required key isSidechain absent",
                        "required key sessionId absent")


def test_a_bookkeeping_line_still_needs_its_agent_id():
    from src.core.subagents import contract

    assert contract.check_line({"type": "fork-context-ref"}).problems == ("required key agentId absent",)
