
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

from src.core.approvals import deliver
from src.core.approvals.extract import extract_dialog
from src.core.beast_prompts.engine import BeastPromptsEngine
from tests.python.approvals.pane_sim import ENTER, PaneSim, fixture

STARTUP = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"


class FakeManager:

    def __init__(self, pane: PaneSim, family: str) -> None:
        self.pane = pane
        self.info = SimpleNamespace(tmux_session="carnivore_t", agent_family=family, session=SimpleNamespace(id="ses_1"))

    async def get_session_info(self, session_id: str):
        return self.info if session_id == "ses_1" else None

    def tmux_socket_name(self) -> str:
        return "throwaway"

    async def send_input(self, data: str, session_id: str) -> None:
        await self.pane.send(data)


class Rig:

    def __init__(self, screen: str, family: str = "claude", enabled: bool = True,
                 startup_screen: Optional[str] = None, monkeypatch=None) -> None:
        self.pane = PaneSim(screen)
        self.family = family
        self.startup_screen = startup_screen
        self.manager = FakeManager(self.pane, family)
        self.now = 0.0
        self.enabled = enabled
        self.answered: List[str] = []
        self.expired = False
        self.expiries = 0
        monkeypatch.setattr(deliver.AttentionEvidenceReader, "_capture",
                            staticmethod(lambda socket, name, history=0: self.pane.render()))
        monkeypatch.setattr(deliver, "SETTLE_SECONDS", 0.0)

        async def on_expiry() -> None:
            self.expiries += 1

        self.engine = BeastPromptsEngine(lambda: self.manager, lambda: None, enabled=lambda _dialog: self.enabled,
                                         on_answered=lambda info, d: self.answered.append(d.fingerprint),
                                         on_expiry=on_expiry, expired=lambda: self.expired,
                                         clock=lambda: self.now)

    def observe(self, at: float, shown: bool = True):
        self.now = at
        dialog = extract_dialog(self.pane.render(), self.family) if shown else None
        evidence = SimpleNamespace(dialog=dialog, startup_screen=self.startup_screen)
        observation = SimpleNamespace(stale=False, evidence=evidence)
        target = SimpleNamespace(session_id="ses_1", key="carnivore_t:1")

        async def run():
            task = self.engine.on_observation(target, observation)
            return await task if task is not None else None

        return asyncio.run(run())


def test_a_settled_permission_prompt_is_answered_plain_yes(monkeypatch):
    rig = Rig(fixture("claude_permission"), monkeypatch=monkeypatch)
    assert rig.observe(0.0) is None
    assert rig.pane.keys == []
    assert rig.observe(2.0) is not None
    assert rig.pane.keys == [ENTER] and rig.pane.pressed == 0
    assert len(rig.answered) == 1


def test_one_fingerprint_is_answered_once_until_it_leaves_the_pane(monkeypatch):
    rig = Rig(fixture("claude_permission"), monkeypatch=monkeypatch)
    rig.observe(0.0)
    rig.observe(2.0)
    assert rig.observe(4.0) is None and rig.observe(6.0) is None
    assert rig.pane.keys == [ENTER]
    rig.observe(8.0, shown=False)
    rig.observe(10.0)
    assert rig.observe(12.0) is not None
    assert rig.pane.keys == [ENTER, ENTER]


def test_codex_command_is_answered_yes_proceed(monkeypatch):
    rig = Rig(fixture("codex_command"), family="codex", monkeypatch=monkeypatch)
    rig.pane.move_cursor(1)
    rig.observe(0.0)
    rig.observe(2.5)
    assert rig.pane.pressed == 0


@pytest.mark.parametrize("name", ["claude_plan_narrow", "claude_single", "claude_multi"])
def test_plan_and_free_text_dialogs_are_never_answered(monkeypatch, name):
    rig = Rig(fixture(name), monkeypatch=monkeypatch)
    for at in (0.0, 2.0, 4.0, 60.0):
        assert rig.observe(at) is None
    assert rig.pane.keys == []


def test_folder_trust_dialog_is_never_answered(monkeypatch):
    rig = Rig((STARTUP / "trust_dialog.txt").read_text(), monkeypatch=monkeypatch)
    for at in (0.0, 2.0, 30.0):
        assert rig.observe(at) is None
    assert rig.pane.keys == []


def test_a_startup_screen_excludes_even_a_plain_yes_dialog(monkeypatch):
    rig = Rig(fixture("claude_permission"), startup_screen="trust", monkeypatch=monkeypatch)
    for at in (0.0, 2.0, 30.0):
        assert rig.observe(at) is None
    assert rig.pane.keys == []


def test_disarmed_scope_presses_nothing(monkeypatch):
    rig = Rig(fixture("claude_permission"), enabled=False, monkeypatch=monkeypatch)
    rig.observe(0.0)
    assert rig.observe(5.0) is None and rig.pane.keys == []


def test_a_dialog_that_changed_since_the_observation_sends_nothing(monkeypatch):
    rig = Rig(fixture("claude_permission"), monkeypatch=monkeypatch)
    rig.observe(0.0)
    rig.now = 2.0
    seen = extract_dialog(rig.pane.render(), "claude")
    rig.pane.lines = [line.replace("touch rigfile", "rm -rf build") for line in rig.pane.lines]
    observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=seen, startup_screen=None))
    target = SimpleNamespace(session_id="ses_1", key="carnivore_t:1")

    async def run():
        task = rig.engine.on_observation(target, observation)
        return await task

    assert asyncio.run(run()) is None
    assert rig.pane.keys == [] and rig.answered == []


def test_an_expired_switch_is_written_off_once(monkeypatch):
    rig = Rig(fixture("claude_single"), monkeypatch=monkeypatch)
    rig.expired = True

    async def run():
        target = SimpleNamespace(session_id="ses_1", key="k")
        obs = SimpleNamespace(stale=False, evidence=SimpleNamespace(dialog=None, startup_screen=None))
        rig.engine.on_observation(target, obs)
        rig.engine.on_observation(target, obs)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert rig.expiries == 1
