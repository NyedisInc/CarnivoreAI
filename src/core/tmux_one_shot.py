
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core.tmux_transport.target import exact_pane_target

logger = structlog.get_logger()

SETTLE_TIMEOUT_SECONDS: float = 3.0

SETTLE_POLL_SECONDS: float = 0.02

QUIET_SECONDS: float = 0.35
QUIET_MAX_SECONDS: float = 4.0
SUBMIT_ATTEMPTS: int = 3
SUBMIT_VERIFY_SECONDS: float = 1.5
SUBMIT_POLL_SECONDS: float = 0.05

ENTER_BYTES: bytes = b"\r"

_PASTE_LOCKS: Dict[str, asyncio.Lock] = {}


def _lock_for(tmux_session: Optional[str]) -> asyncio.Lock:
    return _PASTE_LOCKS.setdefault(tmux_session or "", asyncio.Lock())


class PasteNotSettledError(RuntimeError):
    pass


class PasteNotSubmittedError(RuntimeError):
    pass


DELIVERY_GRACE_SECONDS: float = 6.0
TRANSCRIPT_TAIL_BYTES: int = 8 * 1024 * 1024
SNIPPET_CHARS: int = 80


class _Delivery:

    def __init__(self, snippet: Optional[str], path: Optional[str]) -> None:
        self.snippet, self.path = snippet, path
        self.baseline = self._count()

    @classmethod
    def start(cls, backend: Any, text: str) -> "_Delivery":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        snippet = lines[-1][-SNIPPET_CHARS:] if lines and len(lines[-1]) >= 8 else None
        path: Optional[str] = None
        try:
            from src.core.attention.registry_index import registry_for_session
            from src.core.pack.carry.transcript_scan import transcript_path

            rec = registry_for_session(tmux_name=backend.tmux_session)
            if rec.verdict == "ok" and rec.session_uuid and rec.cwd:
                path = transcript_path(rec.cwd, rec.session_uuid)
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning("one_shot_transcript_unresolved", error=str(exc))
        return cls(snippet, path)

    def _count(self) -> int:
        if not (self.snippet and self.path):
            return 0
        needle = json.dumps(self.snippet, ensure_ascii=False)[1:-1]
        try:
            with open(self.path, "rb") as fh:
                size = os.fstat(fh.fileno()).st_size
                fh.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
                return fh.read().decode("utf-8", "replace").count(needle)
        except OSError:
            return 0

    def landed(self, capture: Optional[bytes]) -> bool:
        if not self.snippet:
            return False
        if capture is not None:
            lines = capture.decode("utf-8", "replace").split("\n")
            from src.core.attention.pane_prompt_box import _is_rule_line

            rules = [i for i, ln in enumerate(lines) if _is_rule_line(ln)]
            outside = lines[:rules[-2] + 1] + lines[rules[-1]:] if len(rules) >= 2 else lines
            if any(self.snippet in ln for ln in outside):
                return True
        return self._count() > self.baseline


def input_box_text(capture: bytes) -> Optional[str]:
    from src.core.attention.pane_prompt_box import _is_rule_line

    lines = capture.decode("utf-8", "replace").split("\n")
    rules = [i for i, ln in enumerate(lines) if _is_rule_line(ln)]
    if len(rules) < 2:
        return None
    body = "\n".join(lines[rules[-2] + 1:rules[-1]]).strip()
    return body.lstrip("\u276f>").strip()


async def _wait_quiet(backend: Any, last: bytes) -> bytes:
    start = time.monotonic()
    stable_since = start
    while time.monotonic() - start < QUIET_MAX_SECONDS:
        await asyncio.sleep(SETTLE_POLL_SECONDS)
        cur = await _capture_pane(backend)
        if cur is None:
            continue
        if cur != last:
            last, stable_since = cur, time.monotonic()
        elif time.monotonic() - stable_since >= QUIET_SECONDS:
            break
    return last


async def _submit_verified(backend: Any, baseline: bytes, delivery: Optional[_Delivery] = None) -> int:
    for press in range(1, SUBMIT_ATTEMPTS + 1):
        await backend._write_via_hex_keys(ENTER_BYTES)
        deadline = time.monotonic() + SUBMIT_VERIFY_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(SUBMIT_POLL_SECONDS)
            cur = await _capture_pane(backend)
            if cur is None:
                continue
            box = input_box_text(cur)
            if box is not None:
                if box == "":
                    return press
            elif cur != baseline:
                return press
            if delivery is not None and delivery.landed(cur):
                return press
    if delivery is not None:
        grace = time.monotonic() + DELIVERY_GRACE_SECONDS
        while time.monotonic() < grace:
            await asyncio.sleep(SUBMIT_VERIFY_SECONDS / 3)
            cur = await _capture_pane(backend)
            if cur is not None and (input_box_text(cur) == "" or delivery.landed(cur)):
                return SUBMIT_ATTEMPTS
    raise PasteNotSubmittedError(
        f"the text is in the input box but {SUBMIT_ATTEMPTS} Enter presses did not submit it")


async def _capture_pane(backend: Any) -> Optional[bytes]:
    rc, out, _ = await backend._run_tmux(
        "capture-pane",
        "-p",
        "-t",
        exact_pane_target(backend.tmux_session),
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
    async with _lock_for(backend.tmux_session):
        if gate is not None:
            await gate()
        before = await _capture_pane(backend)
        if before is None:
            raise PasteNotSettledError(
                "the pane could not be captured before the paste, so a change "
                "could not have been measured afterwards"
            )

        delivery = await asyncio.to_thread(_Delivery.start, backend, text)
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
                box = input_box_text(after) if after is not None else None
                if box:
                    break
                logger.warning(
                    "one_shot_paste_not_settled",
                    tmux_session=backend.tmux_session,
                    bytes=len(data),
                    polls=polls,
                    budget_seconds=SETTLE_TIMEOUT_SECONDS,
                )
                raise PasteNotSubmittedError(
                    "the pane did not visibly change within "
                    f"{SETTLE_TIMEOUT_SECONDS}s of the paste, so the body was "
                    "not submitted"
                )
            await asyncio.sleep(SETTLE_POLL_SECONDS)

        stable = await _wait_quiet(backend, after)
        presses = await _submit_verified(backend, stable, delivery)
        logger.info(
            "one_shot_paste_submitted",
            tmux_session=backend.tmux_session,
            bytes=len(data),
            polls=polls,
            enter_presses=presses,
        )
