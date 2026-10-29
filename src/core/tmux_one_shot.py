
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core.tmux_backend import _safe_target

logger = structlog.get_logger()

SETTLE_TIMEOUT_SECONDS: float = 0.5

SETTLE_POLL_SECONDS: float = 0.02

ENTER_BYTES: bytes = b"\r"

_PASTE_LOCKS: Dict[str, asyncio.Lock] = {}


def _lock_for(tmux_session: Optional[str]) -> asyncio.Lock:
    return _PASTE_LOCKS.setdefault(tmux_session or "", asyncio.Lock())


class PasteNotSettledError(RuntimeError):
    """The pane never visibly changed after the paste, so nothing was submitted.

    Description: a MEASURED negative - the capture ran and kept reading
        the same screen for the whole budget. Distinct from a tmux command
        that could not run at all, which stays a bare ``RuntimeError`` the
        way the rest of this backend treats an unmeasured unknown. The
        route turns this into a 409 ``paste_not_settled``.
    Inputs (constructor): message (str).
    Output: a PasteNotSettledError instance.
    """


async def _capture_pane(backend: Any) -> Optional[bytes]:
    rc, out, _ = await backend._run_tmux(
        "capture-pane",
        "-p",
        "-t",
        _safe_target(backend.tmux_session),
        check=False,
    )
    if rc != 0:
        return None
    return out


async def paste_and_submit(
    backend: Any,
    text: str,
    gate: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """Paste one body into the pane, wait for it to land, then send one Enter.

    Description: the sequence is capture, paste, measure, submit. Every
        step before the submit can fail without anything being submitted,
        which is the safety property this ordering exists for.
    Inputs:
        backend: the ``TmuxBackend`` bound to the target pane.
        text: the body to paste. Already sanitised by
            :mod:`src.core.session_one_shot_gate`; this function does no
            content checking of its own and appends no newline.
        gate: optional async callback that re-checks the caller's paste
            gates. It runs INSIDE the per-pane lock, before anything is
            captured or pasted, so state that changed while this call
            waited for the lock (another paste submitted a dialog-raising
            prompt) is measured again. It refuses by raising; nothing has
            been pasted when it does.
    Output: None.
    Raises:
        PasteNotSettledError: the pane could not be read before the paste,
            or did not change within the budget. No Enter was sent.
        RuntimeError: a tmux command failed outright, raised by the
            backend's own paste and key helpers.
    Concurrency: the sequence is serialised per tmux session, so two
        overlapping one-shots on one pane run one after the other rather
        than sharing the pane's single paste buffer.
    Example: await paste_and_submit(backend, "summarise this repo")
    """
    async with _lock_for(backend.tmux_session):
        if gate is not None:
            await gate()
        before = await _capture_pane(backend)
        if before is None:
            raise PasteNotSettledError(
                "the pane could not be captured before the paste, so a change "
                "could not have been measured afterwards"
            )

        data = text.encode("utf-8")
        await backend._write_via_paste_buffer(data, bracketed=True)

        deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
        polls = 0
        while True:
            after = await _capture_pane(backend)
            polls += 1
            if after is not None and after != before:
                break
            if time.monotonic() >= deadline:
                logger.warning(
                    "one_shot_paste_not_settled",
                    tmux_session=backend.tmux_session,
                    bytes=len(data),
                    polls=polls,
                    budget_seconds=SETTLE_TIMEOUT_SECONDS,
                )
                raise PasteNotSettledError(
                    "the pane did not visibly change within "
                    f"{SETTLE_TIMEOUT_SECONDS}s of the paste, so the body was "
                    "not submitted"
                )
            await asyncio.sleep(SETTLE_POLL_SECONDS)

        await backend._write_via_hex_keys(ENTER_BYTES)
        logger.info(
            "one_shot_paste_submitted",
            tmux_session=backend.tmux_session,
            bytes=len(data),
            polls=polls,
        )
