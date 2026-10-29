
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

from src.core.approvals import dev_channels
from src.core.approvals.answer import AnswerRefused, Choice, answer_dialog
from src.core.approvals.auto_answer.engine import MAX_ATTEMPTS
from src.core.approvals.auto_answer.press import AckRefused
from src.core.approvals.dev_channels import (
    OUR_FLAG_TOKEN, carnivore_answers, is_dev_channels_dialog, launched_with_our_flag, listed_channels)
from tests.python.approvals.auto_helpers import make_engine
from src.core.approvals.extract import DEV_CHANNELS_ACCEPT, extract_dialog

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
PANE_PID = 100


def screen(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def row(pid: int, ppid: int, command: str) -> SimpleNamespace:
    return SimpleNamespace(pid=pid, ppid=ppid, command=command)


OUR_CLAUDE = [row(PANE_PID, 1, "zsh -c claude"), row(101, PANE_PID, f"claude --mcp-config={{}} {OUR_FLAG_TOKEN}")]


def observation(dialog, pane_pid: Optional[int] = PANE_PID, stale: bool = False) -> SimpleNamespace:
    return SimpleNamespace(stale=stale, evidence=SimpleNamespace(
        dialog=dialog, identity=("cloude", "cloude_x", 1700000000, pane_pid, None)))


class Recorder:

    def __init__(self, refuse: int = 0) -> None:
        self.calls: List[tuple] = []
        self.refuse = refuse

    async def __call__(self, session_id: str, fingerprint: str, label: str) -> None:
        self.calls.append((session_id, fingerprint, label))
        if len(self.calls) <= self.refuse:
            raise AckRefused("dialog_changed")


async def feed(ack, session_id: str, obs) -> None:
    task = ack.on_observation(SimpleNamespace(session_id=session_id), obs)
    if task is not None:
        await task


def test_decoder_reads_the_real_warning_at_two_widths() -> None:
    wide = extract_dialog(screen("dev_channels.txt"), "claude")
    narrow = extract_dialog(screen("dev_channels_80.txt"), "claude")
    for dialog in (wide, narrow):
        assert is_dev_channels_dialog(dialog)
        assert listed_channels(dialog) == ("server:carnivore",)
        assert carnivore_answers(dialog)
        assert dialog.cursor == 0 and dialog.rows[0].label == DEV_CHANNELS_ACCEPT
    assert wide.fingerprint == narrow.fingerprint


def test_another_channel_listed_is_never_ours() -> None:
    foreign = extract_dialog(screen("dev_channels_foreign.txt"), "claude")
    assert is_dev_channels_dialog(foreign)
    assert listed_channels(foreign) == ("server:carnivore", "server:evil", "plugin:x@y")
    assert not carnivore_answers(foreign)
    assert foreign.fingerprint != extract_dialog(screen("dev_channels.txt"), "claude").fingerprint


def test_noise_above_the_warning_does_not_hide_the_channels_line() -> None:
    noisy = extract_dialog(screen("dev_channels_noisy.txt"), "claude")
    assert is_dev_channels_dialog(noisy)
    assert listed_channels(noisy) == ("server:carnivore",)
    assert carnivore_answers(noisy)


def test_noise_above_does_not_launder_a_foreign_channel() -> None:
    foreign = screen("dev_channels_noisy.txt").replace("Channels: server:carnivore", "Channels: server:carnivore, server:evil")
    dialog = extract_dialog(foreign, "claude")
    assert listed_channels(dialog) == ("server:carnivore", "server:evil")
    assert not carnivore_answers(dialog)


def test_folder_trust_is_not_this_dialog() -> None:
    trust = extract_dialog(screen("trust_dialog.txt"), "claude")
    assert trust is not None and not is_dev_channels_dialog(trust) and not carnivore_answers(trust)


@pytest.mark.parametrize("rows, expected", [
    (OUR_CLAUDE, True),
    ([row(PANE_PID, 1, "zsh"), row(101, PANE_PID, "claude --dangerously-load-development-channels server:carnivore")], False),
    ([row(PANE_PID, 1, "zsh"), row(101, PANE_PID, f"claude {OUR_FLAG_TOKEN} --dangerously-load-development-channels=server:x")], False),
    ([row(PANE_PID, 1, "zsh"), row(101, PANE_PID, f"claude {OUR_FLAG_TOKEN}x")], False),
    ([row(PANE_PID, 1, "zsh"), row(101, PANE_PID, "claude --resume abc")], False),
    ([row(PANE_PID, 1, "zsh"), row(201, 7, f"claude {OUR_FLAG_TOKEN}")], False),
    (None, None),
])
def test_launch_flag_must_be_our_exact_token(rows, expected) -> None:
    assert launched_with_our_flag(PANE_PID, rows) is expected


def test_unmeasured_pane_pid_is_not_a_yes() -> None:
    assert launched_with_our_flag(None, OUR_CLAUDE) is None


def test_one_answer_per_launch() -> None:
    async def run() -> Recorder:
        answer = Recorder()
        table = {"rows": OUR_CLAUDE}
        ack = make_engine(answer=answer, rows=lambda: table["rows"])
        dialog = extract_dialog(screen("dev_channels.txt"), "claude")
        for _ in range(3):
            await feed(ack, "ses_a", observation(dialog))
        await feed(ack, "ses_a", observation(dialog, pane_pid=PANE_PID))
        restarted = [row(300, 1, "zsh"), row(301, 300, f"claude {OUR_FLAG_TOKEN}")]
        table["rows"] = restarted
        await feed(ack, "ses_a", observation(dialog, pane_pid=300))
        return answer

    answer = asyncio.run(run())
    fingerprint = extract_dialog(screen("dev_channels.txt"), "claude").fingerprint
    assert answer.calls == [("ses_a", fingerprint, DEV_CHANNELS_ACCEPT)] * 2


def test_not_our_channel_gets_no_answer() -> None:
    async def run() -> Recorder:
        answer = Recorder()
        table = {"rows": OUR_CLAUDE}
        ack = make_engine(answer=answer, rows=lambda: table["rows"])
        ours = extract_dialog(screen("dev_channels.txt"), "claude")
        await feed(ack, "ses_f", observation(extract_dialog(screen("dev_channels_foreign.txt"), "claude")))
        await feed(ack, "adopted:mine", observation(ours))
        await feed(ack, "remote:peer-1:ses_r", observation(ours))
        await feed(ack, "ses_s", observation(ours, stale=True))
        await feed(ack, "ses_t", observation(extract_dialog(screen("trust_dialog.txt"), "claude")))
        table["rows"] = [row(PANE_PID, 1, "zsh"), row(101, PANE_PID, "claude --dangerously-load-development-channels server:carnivore")]
        await feed(ack, "ses_h", observation(ours))
        return answer

    assert asyncio.run(run()).calls == []


def test_refusal_retries_within_the_cap() -> None:
    async def run() -> Recorder:
        answer = Recorder(refuse=99)
        table = {"rows": OUR_CLAUDE}
        ack = make_engine(answer=answer, rows=lambda: table["rows"])
        dialog = extract_dialog(screen("dev_channels.txt"), "claude")
        for _ in range(MAX_ATTEMPTS + 3):
            await feed(ack, "ses_r", observation(dialog))
        return answer

    assert len(asyncio.run(run()).calls) == MAX_ATTEMPTS


def test_route_core_presses_enter_once_and_refuses_a_changed_list() -> None:
    ours = extract_dialog(screen("dev_channels.txt"), "claude")

    async def answer(text: str) -> List[str]:
        sent: List[str] = []

        async def capture() -> str:
            return text

        async def send(data: str) -> None:
            sent.append(data)

        try:
            await answer_dialog(family="claude", fingerprint=ours.fingerprint, choice=Choice(option=DEV_CHANNELS_ACCEPT),
                                capture=capture, send=send)
        except AnswerRefused as exc:
            sent.append(f"refused:{exc.reason}")
        return sent

    assert asyncio.run(answer(screen("dev_channels.txt"))) == ["\r"]
    assert asyncio.run(answer(screen("dev_channels_foreign.txt"))) == ["refused:dialog_changed"]


def test_module_names_the_launcher_token() -> None:
    from src.config.mcp_launch import claude_args

    assert claude_args(channel=True)[1] == dev_channels.OUR_FLAG_TOKEN
