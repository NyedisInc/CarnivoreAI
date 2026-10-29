
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.core.attention import watcher as watcher_module
from src.core.attention.evidence import (
    FAMILY_CLAUDE, REASON_QUESTION, REASON_TOOL, STATE_BUSY, STATE_NEEDS_USER, TIER_REGISTRY, AttentionVerdict, Evidence,
)
from src.core.attention.ledger import AttentionLedger
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.attention.watcher import AttentionWatcher, WatchTarget
from src.core.attention_history.recorder import EdgeRecorder
from src.core.attention_history.store import DB_NAME, AttentionHistoryStore
from src.core.session_status import LIVENESS_LIVE
from src.core.session_timeline import attention
from src.core.session_timeline.assemble import Sources, assemble
from src.models.session_timeline import SessionTimeline

START = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
KEY = "cloude_muted@1788294271"
UUID = "11111111-2222-4333-8444-555555555555"


class _Rig:

    def __init__(self, tmp_path: Path, monkeypatch, *, hook_on_toast: bool) -> None:
        self.now, self.verdict, self.toasts = START, AttentionVerdict(STATE_BUSY, REASON_TOOL, TIER_REGISTRY), []
        self.store = AttentionHistoryStore(tmp_path / DB_NAME)
        recorder = EdgeRecorder(self.store, lambda sid, key: UUID)
        monkeypatch.setattr(watcher_module, "resolve_attention", lambda evidence: self.verdict)
        self.target = WatchTarget(session_id="ses_muted", key=KEY)

        def raise_toast(target, kind, transition) -> None:
            self.toasts.append(kind)
            if hook_on_toast:
                recorder.on_transition(target, transition)

        self.watcher = AttentionWatcher(
            list_targets=lambda: [self.target],
            read_evidence=lambda target, now: Evidence(tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=None,
                                           transcript=TranscriptFacts(verdict=FACTS_FOUND), pane=None, now=now),
            raise_toast=raise_toast, set_unread=lambda *a: None, on_busy_edge=lambda *a: None,
            on_transition=None if hook_on_toast else recorder.on_transition,
            read_policy=lambda target: (True, SimpleNamespace(suppresses=True)),
            ledger=AttentionLedger(), now=lambda: self.now, tick_seconds=0.0, registry_directory="/nonexistent-for-this-test")

    def tick(self, verdict: AttentionVerdict, seconds: float = 5.0) -> None:
        self.now, self.verdict = self.now + timedelta(seconds=seconds), verdict
        asyncio.run(self.watcher.tick_once())

    def drive_to_question(self) -> None:
        question = AttentionVerdict(STATE_NEEDS_USER, REASON_QUESTION, TIER_REGISTRY)
        self.tick(self.verdict)
        for _ in range(3):
            self.tick(question)


def test_a_muted_sessions_question_edge_is_recorded_and_in_its_timeline(tmp_path, monkeypatch) -> None:
    rig = _Rig(tmp_path, monkeypatch, hook_on_toast=False)
    rig.drive_to_question()
    assert rig.toasts == [], "the session is muted, so no toast may be raised"
    answer = assemble(Sources(session={"session_uuid": UUID, "row_id": 7, "family": "claude", "current": None},
                              entries=[{"conversation_id": "c1", "current": True, "level": None, "began": None,
                                        "milestones": []}], now=rig.now + timedelta(minutes=1)))
    answer["bars"][0]["started_at"] = START.isoformat()
    spans = SessionTimeline(**attention.attach(answer, tmp_path)).attention
    assert [s.kind for s in spans] == ["question"]
    assert spans[0].end is None


def test_hooking_the_toast_instead_would_lose_the_muted_edge(tmp_path, monkeypatch) -> None:
    rig = _Rig(tmp_path, monkeypatch, hook_on_toast=True)
    rig.drive_to_question()
    assert rig.toasts == []
    assert rig.watcher._ledger.confirmed_state(KEY) == STATE_NEEDS_USER, "the question edge did happen"
    assert not (tmp_path / DB_NAME).exists(), "a recorder on the toast sees nothing from a muted session"
