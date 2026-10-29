
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wfact_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wfact_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.subagent_listing import mark_subagents
from src.core.attention.evidence import FAMILY_CLAUDE, Evidence
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.transcript_facts import (
    FACTS_UNREADABLE,
    TranscriptFacts,
    classify_transcript_records,
)
from src.core.attention.workflow_activity import workflow_active
from src.core.session_status import LIVENESS_LIVE
from src.models import Session, SessionInfo
from tests.test_attention_workflow_busy import (
    CAPTURED_REGISTRY,
    OBSERVED_AT,
    SESSION_UUID,
    _agent_launch,
    _assistant,
    _completion,
    _turn_end,
    _workflow_launch,
)


def _enqueued_completion(timestamp: str, task_id: str, tool_use_id: str) -> Dict[str, Any]:
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": timestamp,
        "sessionId": SESSION_UUID,
        "content": (
            "<task-notification>\n<task-id>" + task_id + "</task-id>\n"
            "<tool-use-id>" + tool_use_id + "</tool-use-id>\n"
            "<output-file><redacted></output-file>\n"
            "<status>completed</status>\n<summary><redacted></summary>\n"
            "</task-notification>"
        ),
    }


def _evidence(records: List[Dict[str, Any]], registry: Optional[Dict[str, Any]] = None,
              facts: Optional[TranscriptFacts] = None) -> Evidence:
    return Evidence(
        tmux_liveness=LIVENESS_LIVE,
        agent_family=FAMILY_CLAUDE,
        registry=parse_registry_record(dict(registry or CAPTURED_REGISTRY), path_pid=61804),
        transcript=facts if facts is not None else classify_transcript_records(records),
        pane=None,
        now=OBSERVED_AT,
    )


def test_an_open_workflow_launch_is_active():
    records = [_workflow_launch("2026-09-22T20:20:20.000Z", "wp7hg6ivq", "toolu_wf")]
    facts = classify_transcript_records(records)
    assert (facts.open_workflows, facts.open_async_agents) == (1, 1)
    assert workflow_active(_evidence(records)) is True


def test_a_trusted_turn_end_naming_a_pending_workflow_is_active():
    records = [_assistant("2026-09-22T20:35:19.000Z"),
               _turn_end("2026-09-22T20:35:19.475Z", pendingWorkflowCount=1)]
    assert classify_transcript_records(records).open_workflows == 0
    assert workflow_active(_evidence(records)) is True


def test_a_completed_workflow_then_a_zero_turn_end_is_inactive():
    records = [
        _workflow_launch("2026-09-22T20:20:20.000Z", "wh01vc9ps", "toolu_wf"),
        _turn_end("2026-09-22T20:20:29.000Z", pendingWorkflowCount=1),
        _enqueued_completion("2026-09-22T20:40:00.000Z", "wh01vc9ps", "toolu_wf"),
        _completion("2026-09-22T20:40:01.000Z", "wh01vc9ps", "toolu_wf"),
        _assistant("2026-09-22T20:40:05.000Z"),
        _turn_end("2026-09-22T20:40:06.000Z"),
    ]
    assert classify_transcript_records(records).found
    assert workflow_active(_evidence(records)) is False


def test_the_enqueued_completion_alone_retires_the_launch():
    records = [
        _workflow_launch("2026-09-22T20:20:20.000Z", "wh01vc9ps", "toolu_wf"),
        _enqueued_completion("2026-09-22T20:40:00.000Z", "wh01vc9ps", "toolu_wf"),
    ]
    assert classify_transcript_records(records).open_workflows == 0


def test_a_background_agent_is_not_a_workflow():
    records = [_agent_launch("2026-09-22T20:33:20.000Z", "a15606cae62d85d87", "toolu_ag")]
    facts = classify_transcript_records(records)
    assert facts.open_async_agents == 1, "the agent is counted as work"
    assert facts.open_workflows == 0
    assert workflow_active(_evidence(records)) is None, "no turn end: not measured"


def test_a_window_with_nothing_measured_is_none_not_false():
    assert workflow_active(_evidence([_assistant("2026-09-22T20:35:19.000Z")])) is None


def test_an_unreadable_transcript_is_none():
    unreadable = TranscriptFacts(verdict=FACTS_UNREADABLE, open_workflows=0)
    assert workflow_active(_evidence([], facts=unreadable)) is None


def test_a_launch_from_an_earlier_claude_process_is_inactive():
    later = dict(CAPTURED_REGISTRY)
    later["startedAt"] = int(datetime(2026, 9, 22, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
    records = [_workflow_launch("2026-09-22T20:20:20.000Z", "wp7hg6ivq", "toolu_wf")]
    assert workflow_active(_evidence(records)) is True, "control: open under its own process"
    assert workflow_active(_evidence(records, registry=later)) is False




class _Watcher:

    def __init__(self, evidence_by_id: Dict[str, Any], stale: bool = False) -> None:
        self._by_id = evidence_by_id
        self._stale = stale
        self.asked: List[str] = []

    def observation_for(self, session_id: str, now: Any = None) -> Any:
        self.asked.append(session_id)
        if session_id not in self._by_id:
            return None
        return SimpleNamespace(stale=self._stale, evidence=self._by_id[session_id])


def _info(session_id: str, family: Optional[str] = "claude") -> SessionInfo:
    return SessionInfo(session=Session(id=session_id, working_dir="/tmp"), agent_family=family)


def _open_evidence() -> Evidence:
    return _evidence([_workflow_launch("2026-09-22T20:20:20.000Z", "w1", "toolu_w1")])


def test_the_field_lands_on_the_wrapper_not_the_session():
    infos = [_info("ses_a")]
    watcher = _Watcher({"ses_a": _open_evidence()})
    mark_subagents(SimpleNamespace(_attention_watcher=watcher), infos)
    body = infos[0].model_dump()
    assert body["workflow_active"] is True
    assert "workflow_active" not in body["session"], "gotcha 1: wrapper only"
    assert watcher.asked == ["ses_a"], "one observation read per row"


def test_codex_unobserved_and_stale_rows_are_null():
    infos = [_info("ses_c", family="codex"), _info("ses_u"), _info("ses_s")]
    mark_subagents(SimpleNamespace(_attention_watcher=_Watcher(
        {"ses_c": _open_evidence(), "ses_s": _open_evidence()})), infos)
    assert [i.workflow_active for i in infos] == [None, None, True], "control: ses_s is fresh"
    stale = [_info("ses_s")]
    mark_subagents(SimpleNamespace(_attention_watcher=_Watcher(
        {"ses_s": _open_evidence()}, stale=True)), stale)
    assert stale[0].workflow_active is None
