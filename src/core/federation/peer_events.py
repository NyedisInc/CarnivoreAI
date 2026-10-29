
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core import session_change_notice
from src.core.federation import peer_event_stream, peer_listing
from src.core.hosts.identity import parse_remote_session_id
from src.models import SessionInfo, WSMessageType

logger = structlog.get_logger()

INTERVAL_SECONDS = 2.0
MAX_STATUS_FRAMES = 20
MIN_ROW_NOTICE_SECONDS = 10.0
_Lights = Tuple[Optional[str], Optional[bool], Optional[str]]


def _lights(rows: List[SessionInfo]) -> Dict[str, Tuple[_Lights, str]]:
    return {r.session.id: ((r.activity_status, r.unread, r.startup_gate), r.host_state) for r in rows}


def _drop_live_lights(frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def live(frame: Dict[str, Any]) -> bool:
        parsed = parse_remote_session_id(str(frame.get("session_id", "")))
        return frame.get("type") == WSMessageType.SESSION_STATUS_CHANGED.value and parsed is not None \
            and parsed[0] in peer_event_stream.LIVE
    return [f for f in frames if not live(f)]


def diff(before: Dict[str, Tuple[_Lights, str]], rows: List[SessionInfo], *,
         last_sent: Optional[Dict[str, float]] = None, clock: float = 0.0) -> List[Dict[str, Any]]:
    now = _lights(rows)
    frames: List[Dict[str, Any]] = []
    structural = set(now) != set(before) or any(now[k][1] != before[k][1] for k in now if k in before)
    by_id = {r.session.id: r for r in rows}
    changed = [sid for sid, (lights, _state) in now.items() if sid in before and lights != before[sid][0]]
    if len(changed) > MAX_STATUS_FRAMES:
        structural, changed = True, []
    sent = last_sent if last_sent is not None else {}
    for sid in changed:
        if clock - sent.get(sid, -MIN_ROW_NOTICE_SECONDS) < MIN_ROW_NOTICE_SECONDS:
            structural = True
            continue
        sent[sid] = clock
        row, lights = by_id[sid], now[sid][0]
        frames.append(session_change_notice.build_status_notice(
            session_id=sid, tmux_session=row.tmux_session, activity_status=lights[0], unread=lights[1],
            startup_gate=lights[2]))
    for gone in [k for k in sent if k not in now]:
        del sent[gone]
    if structural:
        frames.insert(0, session_change_notice.build_structural_notice("peer"))
    return frames


async def run(app_state: Any, open_db: Callable[[], sqlite3.Connection], *, interval: float = INTERVAL_SECONDS) -> None:
    before: Optional[Dict[str, Tuple[_Lights, str]]] = None
    last_sent: Dict[str, float] = {}
    while True:
        try:
            peer_event_stream.sync(app_state, open_db)
            rows = await peer_listing.peer_rows(open_db)
            if before is not None:
                frames = _drop_live_lights(diff(before, rows, last_sent=last_sent, clock=time.monotonic()))
                for frame in frames:
                    session_change_notice.publish(app_state, frame)
                    dispatcher = getattr(app_state, 'crosstalk_dispatcher', None)
                    if dispatcher is not None:
                        dispatcher.on_peer_change(frame.get('session_id'))
            before = _lights(rows)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("peer_events_pass_failed")
        await asyncio.sleep(interval)
