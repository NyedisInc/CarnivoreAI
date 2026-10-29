
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from src.core.session_startup_gate import STARTUP_TAIL_LINES

logger = structlog.get_logger()




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
            error_type=type(exc).__name__,
        )
        return None
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace")
