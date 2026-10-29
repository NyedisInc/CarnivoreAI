
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.approvals.answer import AnswerRefused, Choice, answer_dialog
from src.core.approvals.extract import extract_dialog

PANE = (Path(__file__).resolve().parents[2] / "fixtures" / "approvals" / "claude_permission.txt").read_text()


def run_answer(fingerprint: str, shown: str, sent: list) -> None:
    async def capture() -> str:
        return shown

    async def send(key: str) -> None:
        sent.append(key)

    asyncio.run(answer_dialog(family="claude", fingerprint=fingerprint, choice=Choice(option="Yes"),
                              capture=capture, send=send))


def test_fingerprint_of_command_a_is_refused_when_the_pane_shows_command_b():
    fp_a = extract_dialog(PANE, "claude").fingerprint
    pane_b = PANE.replace("   touch rigfile\n", "   rm -rf build\n")
    sent: list = []
    with pytest.raises(AnswerRefused) as exc:
        run_answer(fp_a, pane_b, sent)
    assert exc.value.reason == "dialog_changed" and sent == []


def test_the_same_command_is_still_answered():
    sent: list = []
    run_answer(extract_dialog(PANE, "claude").fingerprint, PANE, sent)
    assert sent == ["\r"]
