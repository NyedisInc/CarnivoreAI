
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from src.core.mcp import channel as channel_events
from src.core.session_delivery import bring_up, cold_start, delivery_confirm
from src.core.sessions import channel_delivery, guarded_paste

SES = "ses_cold"
TMUX = "carnivore_cold"
BODY = 'a scheduled swarm came due: item 7, "ship it". the huddle changed'


@pytest.fixture(autouse=True)
def fast_and_clean(monkeypatch):
    monkeypatch.setattr(delivery_confirm, "CONFIRM_WINDOW_S", 0.06)
    monkeypatch.setattr(delivery_confirm, "CONFIRM_STEP_S", 0.01)
    monkeypatch.setattr(cold_start, "_READY_AT", {})


def row(status: str = "idle", gate: str = "ready") -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(id=SES), activity_status=status, startup_gate=gate)


class ScriptedOps:

    def __init__(self, gates: List[str]) -> None:
        self.gates = list(gates)
        self.polls = 0

    async def list(self) -> List[Any]:
        gate = self.gates[min(self.polls, len(self.gates) - 1)]
        self.polls += 1
        return [row(gate=gate)]

    async def durable_keys(self, infos: Optional[List[Any]] = None) -> Dict[str, str]:
        return {SES: "key"}


def test_an_idle_row_behind_a_startup_dialog_is_not_ready(monkeypatch):
    ops = ScriptedOps(["unknown", "awaiting_startup_prompt", "ready"])
    got = asyncio.run(bring_up.wait_ready(ops, lambda info, _k: True, "the new session", timeout=5.0, step=0.001))
    assert got == SES and ops.polls == 3
    assert cold_start.is_cold(SES)


def test_a_gate_that_never_reads_ready_times_out():
    ops = ScriptedOps(["unknown"])
    with pytest.raises(bring_up.BringUpFailed):
        asyncio.run(bring_up.wait_ready(ops, lambda info, _k: True, "the new session", timeout=0.02, step=0.005))
    assert not cold_start.is_cold(SES)


class FakeTranscript:

    def __init__(self, tmp_path: Path, landing: List[bool]) -> None:
        self.path = tmp_path / "conv.jsonl"
        self.landing = list(landing)
        self.pushes = 0

    def write(self, text: str) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "queue-operation", "operation": "enqueue", "content": text}) + "\n")
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": f'<channel source="carnivore" list="12">{text}</channel>'}}) + "\n")

    def push(self, tmux_name: Optional[str], content: str, meta: Any) -> bool:
        lands = self.landing[min(self.pushes, len(self.landing) - 1)]
        self.pushes += 1
        if lands:
            self.write(content)
        return True


@pytest.fixture
def conv(tmp_path, monkeypatch):

    def make(landing: List[bool], existing: Optional[str] = None) -> FakeTranscript:
        fake = FakeTranscript(tmp_path, landing)
        if existing is not None:
            fake.write(existing)
        monkeypatch.setattr(channel_events, "REGISTRY", SimpleNamespace(push=fake.push))
        monkeypatch.setattr(delivery_confirm, "transcript_path", lambda _s, _i, _t: fake.path if fake.path.exists() else None)
        return fake

    return make


def confirm(meta: Optional[Dict[str, str]] = None) -> Optional[str]:
    return asyncio.run(delivery_confirm.push_confirmed(SimpleNamespace(), SES, TMUX, BODY, meta or {}))


def test_a_push_that_reaches_the_conversation_is_delivered_once(conv):
    fake = conv([True])
    assert confirm() == delivery_confirm.OUTCOME_DELIVERED and fake.pushes == 1


def test_a_dropped_push_is_resent_once_and_logged_resent(conv):
    fake = conv([False, True])
    assert confirm() == delivery_confirm.OUTCOME_RESENT and fake.pushes == 2


def test_a_push_that_never_arrives_is_unconfirmed_after_one_resend(conv):
    fake = conv([False])
    assert confirm() == delivery_confirm.OUTCOME_UNCONFIRMED and fake.pushes == 2


def test_an_older_identical_body_does_not_confirm_a_new_push(conv):
    fake = conv([False, True], existing=BODY)
    assert confirm() == delivery_confirm.OUTCOME_RESENT and fake.pushes == 2


def test_no_stream_means_no_outcome_so_the_caller_pastes(monkeypatch):
    monkeypatch.setattr(channel_events, "REGISTRY", SimpleNamespace(push=lambda *_a: False))
    monkeypatch.setattr(delivery_confirm, "transcript_path", lambda _s, _i, _t: None)
    assert confirm() is None


def gated_state(monkeypatch, fake: FakeTranscript) -> SimpleNamespace:
    registry = SimpleNamespace(count=lambda: 1, is_open=lambda name: name == TMUX, push=fake.push)
    monkeypatch.setattr(channel_events, "REGISTRY", registry)
    monkeypatch.setattr(channel_events, "channels_enabled", lambda: True)

    async def check(app_state, session_id, text, options=None):
        clean = SimpleNamespace(text=text, byte_length=len(text.encode()), stripped_count=0)
        return guarded_paste.GatedBody(SimpleNamespace(tmux_session=TMUX), None, clean, None, "node", "idle", None)

    monkeypatch.setattr(guarded_paste, "check_through_gates", check)
    return SimpleNamespace(services=SimpleNamespace(registry=SimpleNamespace(get_session=lambda sid: SimpleNamespace(tmux_session=TMUX))))


def test_a_cold_sessions_channel_delivery_carries_the_confirmed_outcome(conv, monkeypatch):
    fake = conv([False, True])
    state = gated_state(monkeypatch, fake)
    cold_start.mark_brought_up(SES)
    got = asyncio.run(channel_delivery.deliver_through_gates(state, SES, BODY, {"source_kind": "huddle"}))
    assert got.delivered_via == "channel" and got.confirmation == delivery_confirm.OUTCOME_RESENT and fake.pushes == 2


def test_a_running_sessions_channel_delivery_is_one_unconfirmed_push(conv, monkeypatch):
    fake = conv([False])
    state = gated_state(monkeypatch, fake)
    got = asyncio.run(channel_delivery.deliver_through_gates(state, SES, BODY, {}))
    assert got.confirmation is None and fake.pushes == 1


def test_the_real_transcript_lookup_finds_a_resumed_conversation_by_its_row(tmp_path, monkeypatch):
    from src.models.sessions import Session

    assert "claude_session_uuid" not in Session.model_fields
    uuid = "4ac1ad63-3808-40c8-90b6-e54eef57dc25"
    root = tmp_path / "projects"
    (root / "-w").mkdir(parents=True)
    transcript = root / "-w" / f"{uuid}.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"content": f'<channel source="carnivore">\n{BODY}\n</channel>'}}) + "\n")
    from src.core.claude_config import transcript_root_search

    monkeypatch.setattr(transcript_root_search, "corpus_roots", lambda _r: (root,))
    state = SimpleNamespace(
        services=SimpleNamespace(registry=SimpleNamespace(get_session=lambda sid: SimpleNamespace(id=sid, working_dir="/w", tmux_session=TMUX))),
        session_manager=SimpleNamespace(claude_uuid_for_tmux_name=lambda name: uuid if name == TMUX else None),
    )
    path = delivery_confirm.transcript_path(state, SES, TMUX)
    assert path == transcript
    assert delivery_confirm.body_seen_after(path, 0, BODY)
