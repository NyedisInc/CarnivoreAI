
from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core import viewer_fanout
from src.core.viewer_fanout import close_viewer_stream as _close_viewer
from src.core.bounded_stream import (
    OFFER_ACCEPTED,
    OFFER_OVERFLOWED,
    BoundedStream,
)
from src.core.session_backend import SessionBackend
from src.models import LogEntry, Session
from src.models.utc_time import utc_now

logger = structlog.get_logger()


def _retire_replaced_reader(session_id: str, backend: SessionBackend) -> None:
    stopped = backend.detach_reader()
    logger.warning(
        "registry_replaced_live_backend",
        session_id=session_id,
        tmux_session=backend.tmux_session,
        reader_stopped=stopped,
        note=(
            "a second backend was registered under an id that already had "
            "one; the old reader was stopped so it cannot publish twice"
        ),
    )

ORPHAN_BUCKET = "__orphan__"



class SessionRegistry:

    def __init__(self, *, log_cap: Callable[[], int]) -> None:
        self.sessions: Dict[str, Session] = {}
        self.backends: Dict[str, SessionBackend] = {}
        self.subscribers: Dict[str, List[BoundedStream]] = {}
        self._parked_viewers: Dict[str, tuple] = {}
        self.log_buffers: Dict[str, List[LogEntry]] = {}
        self.command_counts: Dict[str, int] = {}
        self.last_session_id: Optional[str] = None
        self._hidden: Optional[Callable[[Session], bool]] = None
        self._log_cap = log_cap


    def hide_when(self, predicate: Optional[Callable[[Session], bool]]) -> None:
        self._hidden = predicate

    def is_hidden(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        return session is not None and self._hides(session, self.backends.get(session_id))

    def _hides(self, session: Session, backend: Any) -> bool:
        from src.core.hosts.identity import is_remote_backend

        return self._hidden is not None and not is_remote_backend(backend) and bool(self._hidden(session))

    def listable_ids(self) -> List[str]:
        return [sid for sid in list(self.sessions) if not self.is_hidden(sid)]

    def find_hidden_id(self, target: str) -> Optional[str]:
        for sid, session in list(self.sessions.items()):
            if self.is_hidden(sid) and target in (sid, session.tmux_session):
                return sid
        return None


    def register(
        self, session: Session, backend: Optional[SessionBackend]
    ) -> None:
        self.sessions[session.id] = session
        if backend is not None:
            previous = self.backends.get(session.id)
            if previous is not None and previous is not backend:
                _retire_replaced_reader(session.id, previous)
            self.backends[session.id] = backend
        self.subscribers.setdefault(session.id, [])
        parked = self._parked_viewers.get(session.tmux_session or "")
        if parked is not None and parked[0] == session.id:
            del self._parked_viewers[session.tmux_session]
            self.subscribers[session.id].extend(parked[1])
        self.ensure(session.id)
        if not self._hides(session, self.backends.get(session.id)):
            self.last_session_id = session.id

    def ensure(self, session_id: str) -> None:
        self.log_buffers.setdefault(session_id, [])
        self.command_counts.setdefault(session_id, 0)

    def forget(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.backends.pop(session_id, None)
        for stream in self.subscribers.pop(session_id, []) or []:
            _close_viewer(stream)
        self.log_buffers.pop(session_id, None)
        self.command_counts.pop(session_id, None)
        if self.last_session_id == session_id:
            self.last_session_id = self._newest_listable_id()

    def _newest_listable_id(self) -> Optional[str]:
        for sid in reversed(list(self.sessions)):
            if not self.is_hidden(sid):
                return sid
        return None

    def park_viewers(self, tmux_name: str, session_id: str) -> int:
        streams = self.subscribers.pop(session_id, []) or []
        if streams:
            self._parked_viewers[tmux_name] = (session_id, streams)
        return len(streams)

    def discard_parked(self, tmux_name: str) -> None:
        parked = self._parked_viewers.pop(tmux_name, None)
        for stream in parked[1] if parked else []:
            _close_viewer(stream)


    def get_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def get_backend(self, session_id: str) -> Optional[SessionBackend]:
        return self.backends.get(session_id)

    def list_sessions(self) -> List[Session]:
        return list(self.sessions.values())

    def current_session(self) -> Optional[Session]:
        if (
            self.last_session_id
            and self.last_session_id in self.sessions
            and not self.is_hidden(self.last_session_id)
        ):
            return self.sessions[self.last_session_id]
        sid = self._newest_listable_id()
        self.last_session_id = sid
        return self.sessions[sid] if sid is not None else None

    def current_backend(self) -> Optional[SessionBackend]:
        session = self.current_session()
        if session is None:
            return None
        return self.backends.get(session.id)

    def resolve_session_id(self, session_id: Optional[str]) -> Optional[str]:
        if session_id is not None:
            return session_id if session_id in self.sessions else None
        session = self.current_session()
        return session.id if session is not None else None

    def registered_ids_for_tmux_name(
        self, name: str, also: Optional[str] = None
    ) -> List[str]:
        found = [
            sid
            for sid, backend in self.backends.items()
            if backend.tmux_session == name
        ]
        if also and also in self.backends and also not in found:
            found.append(also)
        return found


    def subscribe(self, session_id: Optional[str] = None, *, resync: bool = False) -> BoundedStream:
        sid = self.resolve_session_id(session_id)
        key = sid if sid is not None else ORPHAN_BUCKET
        stream = viewer_fanout.new_viewer_stream(key, resync=resync)
        self.subscribers.setdefault(key, []).append(stream)
        return stream

    def unsubscribe(
        self, stream: Any, session_id: Optional[str] = None
    ) -> None:
        if session_id is not None:
            subs = self.subscribers.get(session_id)
            if subs and stream in subs:
                subs.remove(stream)
            _close_viewer(stream)
            return
        for subs in self.subscribers.values():
            if stream in subs:
                subs.remove(stream)
                break
        _close_viewer(stream)

    def publish(self, session_id: str, data: bytes) -> None:
        subs = self.subscribers.get(session_id)
        if not subs:
            return
        encoded = base64.b64encode(data).decode("utf-8")
        for stream in list(subs):
            outcome = viewer_fanout.offer_pty(stream, encoded)
            if outcome == OFFER_ACCEPTED:
                continue
            if outcome == OFFER_OVERFLOWED:
                logger.warning(
                    "viewer_output_queue_overflow",
                    session_id=session_id,
                    queued_chunks=viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS,
                )
            try:
                subs.remove(stream)
            except ValueError:
                pass


    def append_log(
        self, session_id: str, content: str, log_type: str = "stdout"
    ) -> LogEntry:
        buf = self.log_buffers.setdefault(session_id, [])
        entry = LogEntry(
            timestamp=utc_now(),
            session_id=session_id,
            content=content,
            log_type=log_type,
        )
        buf.append(entry)
        cap = self._log_cap()
        if len(buf) > cap:
            del buf[: len(buf) - cap]
        return entry

    def recent_logs(self, session_id: str, limit: int) -> List[LogEntry]:
        return self.log_buffers.get(session_id, [])[-limit:]

    def log_line_count(self, session_id: str) -> int:
        return len(self.log_buffers.get(session_id, []))


    def count_command(self, session_id: str) -> int:
        total = self.command_counts.get(session_id, 0) + 1
        self.command_counts[session_id] = total
        return total

    def command_count(self, session_id: str) -> int:
        return self.command_counts.get(session_id, 0)
