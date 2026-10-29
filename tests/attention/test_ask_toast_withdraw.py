
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from src.core.attention.registry_read import parse_registry_record
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.attention_wiring import build_attention_watcher
from src.core.sessions import toast_inbox as toast_inbox_module
from tests.test_attention_wiring import (  # noqa: F401
    RecordingManager,
    busy_pair,
    gathered_file_tiers,
    no_real_pulls,
)

SESSION = "ses_a"
NAME = "cloude_a"

DIALOG_SCREEN = "\n".join([
    "   Do you want to proceed?",
    "   ❯ 1. Yes",
    "     2. No, and tell Claude what to do differently",
    "",
    "   Esc to cancel · Tab to amend",
])

INPUT_SCREEN = None

WORKING_SCREEN = "\n".join([
    "⏸ plan mode on (shift+tab to cycle) · ← 1 agent",
    "◯ Explore the resolver 3m 43s · ↓ 121.8k tokens",
])


def waiting(waiting_for: str):
    at = datetime.now(timezone.utc)
    record = parse_registry_record(
        {
            "pid": 4242,
            "status": "waiting",
            "waitingFor": waiting_for,
            "statusUpdatedAt": int((at - timedelta(seconds=2)).timestamp() * 1000),
            "sessionId": "11111111-2222-3333-4444-555555555555",
            "cwd": "/tmp",
            "tmux": "cloude_a:@0.%0",
            "version": "2.1.266",
        },
        path_pid=4242,
    )
    spoke = at - timedelta(seconds=3) if waiting_for == "permission prompt" else None
    return (record, TranscriptFacts(verdict=FACTS_FOUND,
                                    newest_append_at=at - timedelta(seconds=3),
                                    newest_assistant_at=spoke))


@pytest.fixture()
def harness(monkeypatch, gathered_file_tiers, no_real_pulls):  # noqa: F811
    from src.core import attention_reader
    from src.core.attention import ledger

    monkeypatch.setattr(ledger, "SETTLE_SECONDS", 0.0)
    screen = {"text": WORKING_SCREEN}
    monkeypatch.setattr(attention_reader.AttentionEvidenceReader, "_capture",
                        staticmethod(lambda socket, name, history=0: screen["text"]))
    pushes: list = []
    monkeypatch.setattr(toast_inbox_module.resource_push, "notify", pushes.append)
    frames: list = []

    async def broadcast(session_id, payload):
        frames.append((session_id, json.loads(payload)))

    manager = RecordingManager({SESSION: NAME}, {NAME: busy_pair()})
    watcher = build_attention_watcher(manager, tick_seconds=0.0, broadcast=broadcast)
    return {"manager": manager, "watcher": watcher, "screen": screen,
            "frames": frames, "pushes": pushes}


def tick(h, pair, screen: Optional[str]) -> None:
    h["manager"]._reads[NAME] = pair
    h["screen"]["text"] = screen

    async def one():
        await h["watcher"].tick_once()
        await asyncio.sleep(0)

    asyncio.run(one())


def open_ids(h) -> list:
    return [t.id for t in h["manager"]._toast_inbox.get(SESSION, unacked_only=True)]


def ask_screen(waiting_for: str) -> str:
    return INPUT_SCREEN if waiting_for == "input needed" else DIALOG_SCREEN


def ask(h, waiting_for: str) -> None:
    tick(h, waiting(waiting_for), ask_screen(waiting_for))
    tick(h, waiting(waiting_for), ask_screen(waiting_for))


def raise_ask(h, waiting_for: str = "permission prompt"):
    tick(h, busy_pair(), WORKING_SCREEN)
    ask(h, waiting_for)
    asks = [t for t in h["manager"].toasts if t.kind in ("PermissionRequest", "Notification")]
    assert len(asks) == 1, "the ask raises exactly one alert"
    assert open_ids(h) == [asks[0].id]
    return asks[0]


def test_an_ask_raises_one_alert(harness):
    toast = raise_ask(harness)
    assert toast.kind == "PermissionRequest"


def test_the_alert_stays_while_the_dialog_is_still_open(harness):
    toast = raise_ask(harness)
    tick(harness, waiting("permission prompt"), DIALOG_SCREEN)
    tick(harness, busy_pair(), DIALOG_SCREEN)
    tick(harness, busy_pair(), DIALOG_SCREEN)
    assert open_ids(harness) == [toast.id]
    assert not any(f[1].get("type") == "toast.ack" for f in harness["frames"])


@pytest.mark.parametrize("waiting_for", ["permission prompt", "input needed"])
def test_the_alert_clears_on_the_observed_move_to_working(harness, waiting_for):
    toast = raise_ask(harness, waiting_for)
    assert toast.kind == ("Notification" if waiting_for == "input needed" else "PermissionRequest")
    harness["pushes"].clear()
    tick(harness, busy_pair(), WORKING_SCREEN)
    assert open_ids(harness) == []
    record = harness["manager"]._toast_inbox.get(SESSION)[0]
    assert record.id == toast.id and record.ack_reason == "answered"
    assert "toasts" in harness["pushes"]
    assert (SESSION, {"type": "toast.ack", "toast_id": toast.id}) in [
        (sid, {k: f[k] for k in ("type", "toast_id") if k in f}) for sid, f in harness["frames"]
    ]
    assert harness["watcher"].observation_for(SESSION).verdict.state == "busy"


def test_a_different_ask_withdraws_the_first_and_raises_a_fresh_alert(harness):
    first = raise_ask(harness, "input needed")
    ask(harness, "permission prompt")
    second = [t for t in harness["manager"].toasts if t.kind == "PermissionRequest"]
    assert len(second) == 1 and second[0].id != first.id
    assert open_ids(harness) == [second[0].id]


def test_a_new_ask_after_an_answer_raises_a_fresh_alert(harness):
    first = raise_ask(harness)
    tick(harness, busy_pair(), WORKING_SCREEN)
    ask(harness, "permission prompt")
    asks = [t for t in harness["manager"].toasts if t.kind == "PermissionRequest"]
    assert len(asks) == 2 and asks[1].id != first.id
    assert open_ids(harness) == [asks[1].id]


def test_a_toast_the_user_already_dismissed_sends_nothing(harness):
    toast = raise_ask(harness)
    assert harness["manager"]._toast_inbox.ack(SESSION, toast.id, "dismissed")
    tick(harness, busy_pair(), WORKING_SCREEN)
    record = harness["manager"]._toast_inbox.get(SESSION)[0]
    assert record.ack_reason == "dismissed"
    assert not any(f[1].get("type") == "toast.ack" for f in harness["frames"])


