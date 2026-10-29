
from __future__ import annotations

import asyncio

import pytest

from src.core.tmux_paste_buffer import (
    PasteBufferError,
    is_unknown_no_sanitize_flag,
    paste_buffer_args,
    paste_loaded_buffer,
)

OLD_TMUX_REJECTION = b"command paste-buffer: unknown flag -S\n"


class FakeTmux:

    def __init__(self, answers: list[tuple[int, bytes]]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args: str, check: bool = True) -> tuple[int, bytes, bytes]:
        self.calls.append(args)
        rc, err = self.answers.pop(0)
        return rc, b"", err


def _paste(fake: FakeTmux, *, bracketed: bool) -> None:
    asyncio.run(paste_loaded_buffer(fake, "cloude_x", "=s:0.0", bracketed=bracketed))


def test_raw_paste_passes_no_sanitize_flag_and_keeps_lf():
    assert paste_buffer_args("b", "t", bracketed=False, sanitize_off=True) == [
        "paste-buffer", "-d", "-r", "-S", "-b", "b", "-t", "t",
    ]


def test_bracketed_paste_never_passes_no_sanitize_flag():
    assert paste_buffer_args("b", "t", bracketed=True, sanitize_off=True) == [
        "paste-buffer", "-d", "-p", "-b", "b", "-t", "t",
    ]


def test_the_old_tmux_rejection_is_recognised_and_nothing_else_is():
    assert is_unknown_no_sanitize_flag(OLD_TMUX_REJECTION)
    assert not is_unknown_no_sanitize_flag(b"no buffer cloude_x\n")
    assert not is_unknown_no_sanitize_flag(b"command paste-buffer: unknown flag -Z\n")


def test_a_tmux_37_server_pastes_once_with_the_flag():
    fake = FakeTmux([(0, b"")])
    _paste(fake, bracketed=False)
    assert fake.calls == [("paste-buffer", "-d", "-r", "-S", "-b", "cloude_x", "-t", "=s:0.0")]


def test_an_old_server_is_retried_once_without_the_flag():
    fake = FakeTmux([(1, OLD_TMUX_REJECTION), (0, b"")])
    _paste(fake, bracketed=False)
    assert [("-S" in c) for c in fake.calls] == [True, False]
    assert fake.calls[1] == ("paste-buffer", "-d", "-r", "-b", "cloude_x", "-t", "=s:0.0")


def test_any_other_failure_raises_without_a_retry():
    fake = FakeTmux([(1, b"target pane has exited\n")])
    with pytest.raises(PasteBufferError, match="target pane has exited"):
        _paste(fake, bracketed=False)
    assert len(fake.calls) == 1


def test_a_failed_retry_raises_the_retry_error():
    fake = FakeTmux([(1, OLD_TMUX_REJECTION), (1, b"no buffer cloude_x\n")])
    with pytest.raises(PasteBufferError, match="no buffer cloude_x"):
        _paste(fake, bracketed=False)
    assert len(fake.calls) == 2


def test_the_bracketed_route_is_never_retried():
    fake = FakeTmux([(1, OLD_TMUX_REJECTION)])
    with pytest.raises(PasteBufferError):
        _paste(fake, bracketed=True)
    assert len(fake.calls) == 1
