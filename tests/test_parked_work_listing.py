
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.api.parked_work_listing import parked_summary_for
from src.core.subagents.parked_work import ParkedEntry, ParkedWork


def _watcher_with(evidence: object) -> SimpleNamespace:
    observation = SimpleNamespace(stale=False, evidence=evidence)
    return SimpleNamespace(observation_for=lambda session_id, now: observation)


def _info() -> SimpleNamespace:
    return SimpleNamespace(agent_family="claude", session=SimpleNamespace(id="row-1"))


def test_parked_summary_for_reports_a_top_level_open_background_shell() -> None:
    evidence = SimpleNamespace(
        parked_work=None,
        transcript=SimpleNamespace(open_background_tasks=1),
    )
    summary = parked_summary_for(_watcher_with(evidence), _info(), datetime.now(timezone.utc))
    assert summary is not None
    assert "1 background shell or monitor" in summary
    assert "still running" in summary
    assert "ssh" not in summary and ".output" not in summary


def test_parked_summary_for_prefers_the_subagent_reason_when_both_apply() -> None:
    now = datetime.now(timezone.utc)
    entry = ParkedEntry(
        agent_id="ae6d0000", task_id="bvzswz5xr", kind="shell",
        started_at=now, live=True, agent_type="general-purpose",
        description="build offsite deploy",
    )
    evidence = SimpleNamespace(
        parked_work=ParkedWork("live", live=1, unmeasured=0, entries=(entry,)),
        transcript=SimpleNamespace(open_background_tasks=1),
    )
    summary = parked_summary_for(_watcher_with(evidence), _info(), now)
    assert summary is not None
    assert "sub-agent" in summary
    assert "bvzswz5xr" in summary


def test_parked_summary_for_is_none_with_no_evidence_of_either() -> None:
    evidence = SimpleNamespace(
        parked_work=None,
        transcript=SimpleNamespace(open_background_tasks=0),
    )
    summary = parked_summary_for(_watcher_with(evidence), _info(), datetime.now(timezone.utc))
    assert summary is None
