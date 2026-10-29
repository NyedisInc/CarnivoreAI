
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_SHAPE_UNRECOGNIZED,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.registry_contract import (
    FILE_KIND_REGISTRY,
    check_registry_record,
)
from src.core.attention.registry_record import (
    REG_OK,
    REG_SHAPE_UNRECOGNIZED,
    REG_STALE,
    parse_registry_record,
)
from src.core.attention.registry_index import read_registry_index, registry_for_session
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_NO_RECORD, TranscriptFacts
from src.core.session_status import LIVENESS_LIVE
from src.core.subagents import shape_alert

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "claude_code_shapes_786.json").read_text()
)
RECORD = FIXTURE["registry_record"]
TMUX_NAME = FIXTURE["registry_tmux_name"]
SECRET = "VALUE-SENTINEL-786-registry"


@pytest.fixture(autouse=True)
def _fresh_alerts():
    shape_alert.reset_for_tests()
    yield
    shape_alert.reset_for_tests()


def _with(**changes):
    record = dict(RECORD)
    for key, value in changes.items():
        if value is KeyError:
            record.pop(key, None)
        else:
            record[key] = value
    return record


def test_the_real_structured_record_is_recognised_and_ok():
    check = check_registry_record(RECORD)
    assert check.recognized
    assert "peerFeatures" in check.unknown_keys and "pid" in check.unknown_keys
    assert parse_registry_record(RECORD, path_pid=None).verdict == REG_OK


@pytest.mark.parametrize("changes, problem", [
    ({"status": KeyError}, "required key status absent"),
    ({"status": 7314159265358}, "key status is integer"),
    ({"sessionId": 7314159265358}, "key sessionId is integer"),
    ({"tmux": ["cloude_shape786"]}, "key tmux is array"),
    ({"startedAt": SECRET}, "key startedAt is string"),
    ({"statusUpdatedAt": 1.5}, "key statusUpdatedAt is number"),
    ({"waitingFor": {"kind": SECRET}}, "key waitingFor is object"),
    ({"nameSince": True}, "key nameSince is boolean"),
])
def test_each_shape_change_refuses_by_name_and_never_carries_a_value(changes, problem):
    record = parse_registry_record(_with(**changes), path_pid=40001)
    assert record.verdict == REG_SHAPE_UNRECOGNIZED
    assert record.known is False and record.instance_present is False
    assert record.status is None and record.session_uuid is None and record.pid is None
    assert problem in record.shape_problems
    assert SECRET not in record.detail and "7314159265358" not in record.detail


def test_a_non_object_file_is_a_shape_change():
    record = parse_registry_record(["idle"], path_pid=40001)
    assert record.verdict == REG_SHAPE_UNRECOGNIZED
    assert "top level is array, expected object" in record.shape_problems


def test_the_standing_fallbacks_are_not_shape_changes():
    assert parse_registry_record(_with(pid="x"), path_pid=40001).verdict == REG_OK
    untrusted = parse_registry_record(_with(version=None), path_pid=40001)
    assert untrusted.verdict == REG_OK and untrusted.trusts_pending_count is False
    assert parse_registry_record(_with(waitingFor=None), path_pid=40001).verdict == REG_OK


def test_the_lookup_answers_the_named_state_not_absent(tmp_path):
    pid = os.getpid()
    (tmp_path / ("%d.json" % pid)).write_text(
        json.dumps(_with(pid=pid, status=KeyError)), encoding="utf-8")
    record = registry_for_session(tmux_name=TMUX_NAME, directory=str(tmp_path))
    assert record.verdict == REG_SHAPE_UNRECOGNIZED
    assert "required key status absent" in record.shape_problems


def test_a_crashed_file_with_a_changed_shape_is_still_stale(tmp_path):
    dead = 2 ** 22 + 12345
    while True:
        try:
            os.kill(dead, 0)
            dead += 1
        except ProcessLookupError:
            break
        except PermissionError:
            dead += 1
    (tmp_path / ("%d.json" % dead)).write_text(
        json.dumps(_with(pid=dead, status=KeyError)), encoding="utf-8")
    index = read_registry_index(str(tmp_path))
    assert index[TMUX_NAME].verdict == REG_STALE


def test_a_live_ok_record_outranks_a_shape_refusal_under_the_same_name(tmp_path):
    pid = os.getpid()
    (tmp_path / ("%d.json" % pid)).write_text(json.dumps(_with(pid=pid)), encoding="utf-8")
    (tmp_path / "1.json").write_text(json.dumps(_with(pid=1, status=KeyError)),
                                     encoding="utf-8")
    assert read_registry_index(str(tmp_path))[TMUX_NAME].verdict == REG_OK


def test_the_resolver_reads_a_changed_registry_as_unknown_by_name():
    record = parse_registry_record(_with(status=KeyError), path_pid=40001)
    verdict = resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=record,
        transcript=TranscriptFacts(verdict=FACTS_NO_RECORD), pane=None,
        now=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc),
    ))
    assert verdict.state == STATE_UNKNOWN
    assert verdict.reason == REASON_SHAPE_UNRECOGNIZED


def test_one_warning_per_distinct_mismatch_and_the_note_names_this_contract(tmp_path):
    seen = []
    shape_alert.set_listener(seen.append)
    try:
        for _ in range(3):
            parse_registry_record(_with(status=7314159265358), path_pid=40001)
        parse_registry_record(_with(sessionId=7314159265358), path_pid=40001)
    finally:
        shape_alert.set_listener(None)
    assert [entry["file_kind"] for entry in seen] == [FILE_KIND_REGISTRY] * 2
    note = shape_alert.render_note(check_registry_record(_with(status=1)), "2.1.283")
    assert "src/core/attention/registry_contract.py" in note
    assert "pid registry record" in note
