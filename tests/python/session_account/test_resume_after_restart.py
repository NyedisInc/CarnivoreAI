from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.account_switch import resume_after_restart as rar
from src.core.session_startup_gate import GATE_READY


def _info(name: str, status: str = "idle", gate: str = GATE_READY) -> SimpleNamespace:
    return SimpleNamespace(tmux_session=name, startup_gate=gate, activity_status=status,
                           session=SimpleNamespace(id=f"ses_{name}"))


class _Ops:

    def __init__(self) -> None:
        self.reads = 0

    async def list(self):
        self.reads += 1
        first = self.reads == 1
        return [_info("other"), _info("carnivore_x", status="unknown", gate="awaiting_startup_prompt" if first else GATE_READY)]

    async def durable_keys(self, infos):
        return {}


@pytest.fixture
def wired(monkeypatch):
    ops = _Ops()
    sent: list = []
    refusals = [HTTPException(409, "busy")]

    async def paste(request, session_id, text, *, fresh_dialog_check=False):
        if refusals:
            raise refusals.pop()
        sent.append((session_id, text, fresh_dialog_check))

    monkeypatch.setattr(rar.bring_up, "ops_for_app", lambda _state: ops)
    monkeypatch.setattr("src.api.one_shot_routes.paste_through_gates", paste)
    return sent


def test_waits_past_the_startup_screens_then_types_resume_once_with_a_fresh_screen_check(wired):
    assert asyncio.run(rar.resume_when_ready(object(), "carnivore_x", settle=0, retry=0, step=0)) is True
    assert wired == [("ses_carnivore_x", "resume", True)]


def test_beast_off_schedules_nothing(monkeypatch):
    monkeypatch.setattr(rar, "beast_enabled", lambda: False)
    assert rar.schedule(object(), "carnivore_x") is False
