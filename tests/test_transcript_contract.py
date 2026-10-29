
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_SHAPE_UNRECOGNIZED,
    STATE_DONE_IDLE,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_contract import (
    FILE_KIND_TRANSCRIPT,
    check_transcript_line,
    check_window,
)
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_SHAPE_UNRECOGNIZED,
    read_transcript_facts,
)
from src.core.session_status import LIVENESS_LIVE
from src.core.subagents import parked_launches, shape_alert

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "claude_code_shapes_786.json").read_text()
)
LINES = FIXTURE["transcript_lines"]

SECRET = "VALUE-SENTINEL-786-must-never-leak"

NOW = datetime(2026, 9, 27, 12, 0, 40, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_alerts():
    shape_alert.reset_for_tests()
    yield
    shape_alert.reset_for_tests()


def _index(kind: str, subtype: str = None) -> int:
    for position, line in enumerate(LINES):
        if line.get("type") == kind and (subtype is None or line.get("subtype") == subtype):
            return position
    raise AssertionError("fixture has no %s line" % kind)


def _mutated(kind: str, mutate, subtype: str = None):
    lines = copy.deepcopy(LINES)
    mutate(lines[_index(kind, subtype)])
    return lines


def _write(tmp_path: Path, lines) -> str:
    path = tmp_path / "conversation.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return str(path)


def test_every_real_structured_fixture_line_is_recognised():
    for line in LINES:
        check = check_transcript_line(line)
        assert check is None or check.recognized, (line.get("type"), check)
    assert check_window(LINES, report=False) == ()


def test_a_type_the_watcher_does_not_read_is_not_checked():
    assert check_transcript_line({"type": "mode", "anything": [1, {"x": None}]}) is None


MUTATIONS = [
    ("system", "turn_duration",
     lambda r: r.update(pendingBackgroundAgentCount=SECRET),
     "key pendingBackgroundAgentCount is string"),
    ("system", "turn_duration", lambda r: r.pop("version"),
     "required key version absent"),
    ("system", "turn_duration", lambda r: r.pop("subtype"),
     "required key subtype absent"),
    ("assistant", None, lambda r: r["message"].update(content={"text": SECRET}),
     "key message.content is object"),
    ("assistant", None, lambda r: r["message"]["content"][2].update(id=7314159265358),
     "key message.content[tool_use].id is integer"),
    ("assistant", None, lambda r: r["message"]["content"][2].pop("name"),
     "required key message.content[tool_use].name absent"),
    ("assistant", None, lambda r: r.pop("timestamp"), "required key timestamp absent"),
    ("user", None, lambda r: r.pop("message"), "required key message absent"),
    ("user", None, lambda r: r.update(isSidechain=SECRET), "key isSidechain is string"),
    ("queue-operation", None, lambda r: r.update(operation=7314159265358),
     "key operation is integer"),
    ("attachment", None, lambda r: r["attachment"].pop("type"),
     "required key attachment.type absent"),
    ("attachment", None, lambda r: r["attachment"].update(prompt=7314159265358),
     "key attachment.prompt is integer"),
]


@pytest.mark.parametrize("kind, subtype, mutate, problem", MUTATIONS)
def test_each_shape_change_is_named_by_field_and_type_never_value(kind, subtype, mutate, problem):
    lines = _mutated(kind, mutate, subtype)
    problems = check_window(lines, report=False)
    assert problem in problems
    assert SECRET not in " ".join(problems)
    assert "7314159265358" not in " ".join(problems)


@pytest.mark.parametrize("position, mutate, problem", [
    (3, lambda r: r["toolUseResult"].update(backgroundTaskId=7314159265358),
     "key toolUseResult.backgroundTaskId is integer"),
    (4, lambda r: r["toolUseResult"].update(isAsync=SECRET), "key toolUseResult.isAsync is string"),
    (5, lambda r: r["toolUseResult"].update(timeoutMs=SECRET), "key toolUseResult.timeoutMs is string"),
    (6, lambda r: r["toolUseResult"].update(task_id=7314159265358),
     "key toolUseResult.task_id is integer"),
    (3, lambda r: r["message"]["content"][0].pop("tool_use_id"),
     "required key message.content[tool_result].tool_use_id absent"),
    (7, lambda r: r.update(origin={"kind": 7314159265358}), "key origin.kind is integer"),
])
def test_the_launch_and_retirement_shapes_turn_counts_decodes_are_contracted(position, mutate, problem):
    lines = copy.deepcopy(LINES)
    mutate(lines[position])
    assert problem in check_window(lines, report=False)


def test_a_line_that_is_not_an_object_or_has_no_type_is_unrecognised():
    assert "top level is array, expected object" in check_transcript_line([1]).problems
    assert "required key type absent" in check_transcript_line({"timestamp": "x"}).problems
    assert "key type is integer" in check_transcript_line({"type": 3}).problems


def test_the_reader_answers_found_on_the_real_shape_and_the_named_state_on_a_mutation(tmp_path):
    good = read_transcript_facts(_write(tmp_path, LINES))
    assert good.verdict == FACTS_FOUND
    assert good.pending_background_agents == 0
    assert good.shape_problems == ()

    broken = read_transcript_facts(_write(tmp_path, _mutated(
        "assistant", lambda r: r["message"].update(content={"text": SECRET}))))
    assert broken.verdict == FACTS_SHAPE_UNRECOGNIZED
    assert broken.pending_background_agents is None
    assert broken.pending_workflows is None
    assert broken.found is False
    assert "key message.content is object" in broken.shape_problems
    assert SECRET not in broken.detail


def _registry_idle():
    record = dict(FIXTURE["registry_record"])
    record["statusUpdatedAt"] = int((NOW - timedelta(seconds=10)).timestamp() * 1000)
    return parse_registry_record(record, path_pid=None)


def _resolve(facts):
    return resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
        registry=_registry_idle(), transcript=facts, pane=None, now=NOW,
    ))


def test_a_changed_shape_can_never_read_as_done_it_reads_unknown_by_name(tmp_path):
    control = _resolve(read_transcript_facts(_write(tmp_path, LINES)))
    assert control.state == STATE_DONE_IDLE

    lines = _mutated("assistant", lambda r: r["message"].update(content={"text": SECRET}))
    from src.core.attention.transcript_facts import classify_transcript_records
    uncontracted = classify_transcript_records(lines, window_is_whole_file=True)
    assert _resolve(uncontracted).state == STATE_DONE_IDLE

    verdict = _resolve(read_transcript_facts(_write(tmp_path, lines)))
    assert verdict.state == STATE_UNKNOWN, (verdict.reason, verdict.detail)
    assert verdict.reason == REASON_SHAPE_UNRECOGNIZED


def test_one_distinct_mismatch_is_reported_once_however_often_it_is_read(tmp_path):
    seen = []
    shape_alert.set_listener(seen.append)
    try:
        path = _write(tmp_path, _mutated(
            "system", lambda r: r.update(pendingBackgroundAgentCount=SECRET), "turn_duration"))
        for _ in range(3):
            read_transcript_facts(path)
    finally:
        shape_alert.set_listener(None)
    assert len(seen) == 1
    assert seen[0]["file_kind"] == FILE_KIND_TRANSCRIPT
    assert seen[0]["claude_code_version"] == "2.1.283"
    assert SECRET not in json.dumps(seen[0])


def test_a_sub_agent_launch_whose_shape_changed_is_kept_open_and_unmeasured(tmp_path):
    import io

    good = copy.deepcopy(LINES[3])
    ledger, _ = parked_launches._scan_launches(
        io.BytesIO((json.dumps(good) + "\n").encode()), parked_launches._Ledger(), "a1")
    assert [launch.output_path for launch in ledger.launches.values()] == ["/tmp/placeholder.output"]

    broken = copy.deepcopy(LINES[3])
    broken["toolUseResult"]["backgroundTaskId"] = 7314159265358
    ledger, _ = parked_launches._scan_launches(
        io.BytesIO((json.dumps(broken) + "\n").encode()), parked_launches._Ledger(), "a1")
    (launch,) = ledger.launches.values()
    assert launch.output_path is None
    assert launch.task_id.startswith("shape_unrecognized:")


def _remote_trigger_result(status):
    line = copy.deepcopy(LINES[3])
    line["toolUseResult"] = {"status": status, "json": "{}"}
    return line


def test_another_tools_integer_status_is_its_payload_not_a_shape_change(tmp_path):
    lines = copy.deepcopy(LINES)
    lines.insert(4, _remote_trigger_result(200))
    assert check_transcript_line(lines[4]).problems == ()
    facts = read_transcript_facts(_write(tmp_path, lines))
    assert facts.verdict == FACTS_FOUND, facts.shape_problems
    verdict = _resolve(facts)
    assert verdict.state == STATE_DONE_IDLE, (verdict.reason, verdict.detail)


def test_an_integer_status_on_a_task_shape_is_still_a_shape_change():
    line = copy.deepcopy(LINES[4])
    line["toolUseResult"]["status"] = 200
    assert "key toolUseResult.status is integer" in check_transcript_line(line).problems
