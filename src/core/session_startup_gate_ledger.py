
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.session_startup_gate import STARTUP_TAIL_LINES

logger = logging.getLogger(__name__)




PREFETCH_MAX_AGE_SECONDS: float = 5.0


@dataclass
class _InstanceRecord:

    epoch: Optional[int] = None
    pane_pid: Optional[int] = None
    first_hook_at: Optional[datetime] = None
    last_tail_match: Optional[bool] = None
    last_tail_at: Optional[datetime] = None


class StartupGateLedger:

    def __init__(self) -> None:
        self._records: dict[str, _InstanceRecord] = {}
        self._prefetched_tails: dict[str, tuple[float, Optional[str]]] = {}

    def record_hook(
        self,
        tmux_name: Optional[str],
        *,
        epoch: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> None:
        if not tmux_name:
            return
        record = self._records.setdefault(tmux_name, _InstanceRecord())
        if epoch is not None:
            if record.epoch is not None and record.epoch != int(epoch):
                record = _InstanceRecord()
                self._records[tmux_name] = record
            record.epoch = int(epoch)
        if record.first_hook_at is None:
            record.first_hook_at = now or datetime.utcnow()

    def observe_instance(
        self,
        tmux_name: Optional[str],
        *,
        epoch: Optional[int],
        pane_pid: Optional[int],
    ) -> None:
        if not tmux_name:
            return
        record = self._records.get(tmux_name)
        if record is None:
            return
        moved = (
            epoch is not None
            and record.epoch is not None
            and int(epoch) != record.epoch
        ) or (
            pane_pid is not None
            and record.pane_pid is not None
            and int(pane_pid) != record.pane_pid
        )
        if moved:
            self._records[tmux_name] = _InstanceRecord(
                epoch=int(epoch) if epoch is not None else None,
                pane_pid=int(pane_pid) if pane_pid is not None else None,
            )
            return
        if epoch is not None:
            record.epoch = int(epoch)
        if pane_pid is not None:
            record.pane_pid = int(pane_pid)

    def first_hook_at(self, tmux_name: Optional[str]) -> Optional[datetime]:
        if not tmux_name:
            return None
        record = self._records.get(tmux_name)
        return record.first_hook_at if record else None

    def record_tail_read(
        self,
        tmux_name: Optional[str],
        *,
        matched: Optional[bool],
        now: Optional[datetime] = None,
    ) -> None:
        """Remember what the last pane-tail read for this instance found.

            Recording the verdict lets the caller re-read at its own
            interval instead of at the listing's, and lets the gate keep
            ANSWERING in between rather than falling back to ``unknown``
            - a throttle that made the row flap between ``ready`` and
            ``unknown`` would be a worse bug than the cost it saved.

            A ``matched`` of None - the capture failed, or produced
            nothing - CHANGES NOTHING AT ALL. It neither overwrites the
            verdict nor stamps the clock, which is the same rule the rest
            of this codebase applies to a reading that did not answer:
            not having managed to look is not evidence, so it must not
            erase what was measured last time, and it must not start a
            throttle window either. Writing the None through would leave
            the row answering ``unknown`` for the rest of the window
            while a perfectly good measurement sat one field away.
        Inputs:
            tmux_name: tmux session name; falsy is a no-op.
            matched: True (a startup-prompt marker was on the pane),
                False (the pane was read and held none), None (the read
                did not produce anything).
            now: injectable clock. Defaults to ``datetime.utcnow()``.
        Output: None.
        Example:
            >>> led = StartupGateLedger()
            >>> led.record_tail_read("a", matched=False)
            >>> led.last_tail_match("a")
            False
        """
        if not tmux_name:
            return
        if matched is None:
            return
        record = self._records.setdefault(tmux_name, _InstanceRecord())
        record.last_tail_match = matched
        record.last_tail_at = now or datetime.utcnow()

    def last_tail_match(self, tmux_name: Optional[str]) -> Optional[bool]:
        if not tmux_name:
            return None
        record = self._records.get(tmux_name)
        return record.last_tail_match if record else None

    def tail_age_seconds(
        self, tmux_name: Optional[str], *, now: Optional[datetime] = None
    ) -> Optional[float]:
        if not tmux_name:
            return None
        record = self._records.get(tmux_name)
        if record is None or record.last_tail_at is None:
            return None
        delta = (now or datetime.utcnow()) - record.last_tail_at
        return max(0.0, delta.total_seconds())

    def stash_prefetched_tail(self, tmux_name: str, tail: Optional[str]) -> None:
        self._prefetched_tails[tmux_name] = (time.monotonic(), tail)

    def pop_prefetched_tail(self, tmux_name: str) -> tuple[bool, Optional[str]]:
        stamped = self._prefetched_tails.pop(tmux_name, None)
        if stamped is None or time.monotonic() - stamped[0] > PREFETCH_MAX_AGE_SECONDS:
            return False, None
        return True, stamped[1]

    def forget(self, tmux_name: Optional[str]) -> None:
        if tmux_name:
            self._records.pop(tmux_name, None)




def capture_pane_tail(
    *, socket: str, name: str, lines: int = STARTUP_TAIL_LINES
) -> Optional[str]:
    """Read a pane's recent scrollback as text, or None if it could not be.

    Description: one ``tmux capture-pane`` through a bare
        ``TmuxBackend.for_external`` - no attach, no pipe-pane, nothing
        kept afterwards. This is the same cheap probe
        ``SessionManager._detect_agent_type_from_pane`` uses, extracted
        here so the capture and the thing that reads it are not written
        twice.

        NEVER RAISES, and returns None rather than "" on failure. A
        listing poll must not fail because one pane could not be read,
        and "" would be handed to ``detect_startup_prompt`` as text that
        was successfully read and found empty - which would answer
        ``ready`` for a pane nobody actually managed to look at.
    Inputs:
        socket: tmux socket name (always this app's own socket).
        name: tmux session name.
        lines: how many lines of scrollback to ask for.
    Output:
        str | None - decoded pane text, or None when the capture failed
        or produced nothing.
    Example:
        capture_pane_tail(socket='cloude', name='cloude_a')
    """
    from src.core.tmux_backend import TmuxBackend

    try:
        probe = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path.home(),
            socket_name=socket,
        )
        raw = probe.capture_scrollback(lines=lines)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "startup_gate_capture_failed",
            session=name,
            socket=socket,
            error=str(exc),
        )
        return None
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace")
