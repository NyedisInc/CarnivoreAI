
from __future__ import annotations

import asyncio
import json
import time
import unicodedata
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Tuple

import structlog

from src.core import session_change_notice
from src.core.attention.raise_gate import resolve_raise
from src.core.event_hub import get_hub
from src.core.session_output import tap as output_tap
from src.core.session_output.escape_scanner import EscapeScanner, Event
from src.core.stream_redactor import redact_whole
from src.models import ToastNewMessage
from src.models.websocket import WSMessageType

logger = structlog.get_logger(__name__)

NOTIFY_TYPE = "session.terminal_notice"
FRAME_PROGRESS = WSMessageType.SESSION_PROGRESS.value
FRAME_BELL = WSMessageType.SESSION_BELL.value
TITLE_BYTES, BODY_BYTES = 160, 500
BURST, REFILL_SECONDS = 3, 5.0
PROGRESS_SILENCE_SECONDS = 15.0
PROGRESS_GAP_SECONDS = 1.0
BELL_GAP_SECONDS = 2.0
QUEUE_MAX = 256
QUIET_FAMILIES = frozenset({"claude", "codex"})
PROGRESS_STATES = {"1": "normal", "2": "error", "3": "indeterminate", "4": "paused"}
DEFAULT_TITLE = "terminal notice"


def clean(text: str, limit: Optional[int] = None) -> str:
    kept = "".join(" " if ch in "\t\n\r" else ch for ch in text
                   if ch in "\t\n\r" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co"))
    kept = " ".join(kept.split())
    return kept if limit is None else kept.encode("utf-8")[:limit].decode("utf-8", "ignore")


def safe_text(text: str, limit: int) -> str:
    return clean(redact_whole(clean(text)), limit)


class _Bucket:

    __slots__ = ("tokens", "at")

    def __init__(self, now: float) -> None:
        self.tokens, self.at = float(BURST), now

    def take(self, now: float) -> bool:
        self.tokens = min(float(BURST), self.tokens + (now - self.at) / REFILL_SECONDS)
        self.at = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class TerminalNotices:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._scanners: Dict[str, EscapeScanner] = {}
        self._queue: Deque[Tuple[str, Event]] = deque(maxlen=QUEUE_MAX)
        self._scheduled = False
        self._buckets: Dict[str, _Bucket] = {}
        self._progress: Dict[str, Tuple[Tuple[Optional[str], Optional[int]], float]] = {}
        self._progress_shown: Dict[str, Tuple[Tuple[Optional[str], Optional[int]], float]] = {}
        self._bell_at: Dict[str, float] = {}
        self._status: Dict[str, str] = {}
        self._resume_ids: Dict[str, str] = {}
        self._by_tmux: Dict[str, str] = {}
        self._family: Dict[str, Optional[str]] = {}
        self._manager: Any = None
        self._app_state: Any = None
        self._send: Optional[Callable[[str, str], None]] = None
        self.recorded_quiet = 0
        self._attached = False

    def attach(self, manager: Any, app_state: Any, send: Callable[[str, str], None]) -> None:
        self._manager, self._app_state, self._send = manager, app_state, send
        if not self._attached:
            self._attached = True
            output_tap.TAP.add(self.on_output)

    def on_output(self, session_id: str, data: bytes) -> None:
        scanner = self._scanners.get(session_id)
        if scanner is None:
            scanner = self._scanners[session_id] = EscapeScanner()
        events = scanner.feed(data)
        if not events:
            return
        self._queue.extend((session_id, e) for e in events)
        if not self._scheduled:
            self._scheduled = True
            asyncio.get_running_loop().call_soon(self.drain)

    def drain(self) -> None:
        self._scheduled = False
        while self._queue:
            session_id, event = self._queue.popleft()
            try:
                if event.kind == "notify":
                    self._notify(session_id, event)
                elif event.kind == "progress":
                    value = (PROGRESS_STATES.get(event.title), event.percent if event.title in "124" else None)
                    self._set_progress(session_id, value if value[0] else (None, None))
                elif event.kind == "status":
                    self._status[session_id] = event.title
                    if event.body:
                        self._resume_ids[session_id] = event.body
                else:
                    self._bell(session_id)
            except (ValueError, KeyError, RuntimeError, TypeError) as exc:
                logger.warning("terminal_notice_failed", session_id=session_id, kind=event.kind,
                               error_type=type(exc).__name__)

    def _notify(self, session_id: str, event: Event) -> None:
        if self._family.get(session_id) in QUIET_FAMILIES:
            self.recorded_quiet += 1
            logger.debug("terminal_notice_recorded_quiet", session_id=session_id)
            return
        now = self._clock()
        bucket = self._buckets.get(session_id)
        if bucket is None:
            bucket = self._buckets[session_id] = _Bucket(now)
        if not bucket.take(now):
            return
        title = safe_text(event.title, TITLE_BYTES) or DEFAULT_TITLE
        body = safe_text(event.body, BODY_BYTES) or None
        manager = self._manager
        if manager is None:
            return
        gate = resolve_raise("Notification",
                             policy_store_attached=getattr(manager, "_notification_policy_store", None) is not None,
                             policy=manager.notification_policy_stamp(session_id))
        if not gate.raises_toast:
            return
        toast = manager.record_toast(session_id=session_id, kind="Notification", title=title, body=body,
                                     notify_type=NOTIFY_TYPE)
        payload = ToastNewMessage(toast=toast).model_dump_json()
        if self._send is not None:
            self._send(session_id, payload)
        session_change_notice.publish(self._app_state, json.loads(payload))

    def _set_progress(self, session_id: str, value: Tuple[Optional[str], Optional[int]]) -> None:
        if value[0] is None:
            self._progress.pop(session_id, None)
        else:
            self._progress[session_id] = (value, self._clock())
        self._send_progress(session_id, force=False)

    def _send_progress(self, session_id: str, force: bool) -> None:
        held = self._progress.get(session_id)
        value = held[0] if held else (None, None)
        shown, at = self._progress_shown.get(session_id, ((None, None), float("-inf")))
        now = self._clock()
        if value == shown or (not force and now - at < PROGRESS_GAP_SECONDS):
            return
        self._progress_shown[session_id] = (value, now)
        self._frame({"type": FRAME_PROGRESS, "session_id": session_id, "state": value[0], "percent": value[1]})

    def _bell(self, session_id: str) -> None:
        now = self._clock()
        if now - self._bell_at.get(session_id, -BELL_GAP_SECONDS) < BELL_GAP_SECONDS:
            return
        self._bell_at[session_id] = now
        self._frame({"type": FRAME_BELL, "session_id": session_id})

    def _frame(self, frame: Dict[str, Any]) -> None:
        hub = get_hub(self._app_state)
        if hub is not None:
            hub.publish(frame)

    def on_observation(self, session_id: str, display: str, family: Optional[str],
                       tmux_name: Optional[str] = None) -> None:
        self._family[session_id] = family
        if tmux_name:
            self._by_tmux[tmux_name] = session_id
        held = self._progress.get(session_id)
        if held is not None and (display == "dead" or self._clock() - held[1] > PROGRESS_SILENCE_SECONDS):
            self._set_progress(session_id, (None, None))
        self._send_progress(session_id, force=True)
        if display == "dead":
            for table in (self._scanners, self._buckets, self._bell_at, self._status, self._progress_shown):
                table.pop(session_id, None)

    def status_for(self, session_id: str) -> Optional[str]:
        return self._status.get(session_id)

    def resume_id_for(self, session_id: str) -> Optional[str]:
        return self._resume_ids.get(session_id)

    def resume_id_for_tmux(self, tmux_name: str) -> Optional[str]:
        session_id = self._by_tmux.get(tmux_name)
        return self._resume_ids.get(session_id) if session_id else None

    def progress_for(self, session_id: str) -> Optional[Tuple[Optional[str], Optional[int]]]:
        held = self._progress.get(session_id)
        return held[0] if held else None


NOTICES = TerminalNotices()
