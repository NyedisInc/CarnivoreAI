"""Broadcast one command line to a Layout's members (issue #837).

THE SEND IS THE ONE-SHOT'S, NOT A SECOND ONE. Each pane receives the text
through ``SessionBackend.paste_and_submit`` (``src/core/tmux_one_shot.py``):
argv to tmux (never a shell string), the paste route forced, the Enter sent
only after the pane is MEASURED to have changed, and the whole sequence
serialised per pane. A pane that never showed the paste gets no Enter and
reports ``failed`` / ``paste_not_settled``.

A PANE STOPPED ON A DIALOG IS REFUSED, NOT TYPED INTO. An agent showing a
permission prompt or its folder trust question is waiting on a KEY, and a
pasted line would answer it. Read off the same live listing the status
lights paint from (``activity_status == 'question'``, ``startup_gate ==
'awaiting_startup_prompt'``, on the WRAPPER per gotcha 1), the one-shot
gate's rungs 3 and 4 for the same reason. A plain shell has neither, so a
shell prompt receives the line like a typed command, which is the point.
"""

from __future__ import annotations

import asyncio
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import structlog

from src.core.layouts import store as store
from src.core.db import table_exists, transaction
from src.core.layouts.broadcast_ddl import LAYOUT_BROADCAST_OFF_TABLE
from src.core.session_startup_gate import GATE_AWAITING
from src.core.session_status import STATUS_DEAD, STATUS_QUESTION
from src.core.tmux_one_shot import PasteNotSettledError
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

TEXT_MAX_BYTES = 4096

_ALLOWED_CONTROL = "\t"

SENT = "sent"
SKIPPED_OFF = "skipped_off"
SKIPPED_NOT_LIVE = "skipped_not_live"
FAILED = "failed"


class BroadcastRefused(store.LayoutError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BroadcastUnavailable(store.LayoutError):
    pass


@dataclass(frozen=True)
class MemberOutcome:

    session_row_id: int
    session_uuid: str
    status: str
    code: Optional[str] = None


def check_text(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BroadcastRefused("broadcast_text_empty", "there is nothing to send")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError:
        raise BroadcastRefused("broadcast_text_control",
                               "the text holds a character that cannot be encoded") from None
    if size > TEXT_MAX_BYTES:
        raise BroadcastRefused("broadcast_text_too_large",
                               f"the text is {size} bytes and the limit is {TEXT_MAX_BYTES}")
    if any(unicodedata.category(ch) == "Cc" and ch != _ALLOWED_CONTROL for ch in raw):
        raise BroadcastRefused("broadcast_text_control",
                               "the text holds a control character (a newline or an escape)")
    return raw


def set_member_broadcast(conn: sqlite3.Connection, layout_uuid: str, session_uuid: str,
                         enabled: bool, *, now: Optional[str] = None) -> store.WriteResult:
    store.require_tables(conn)
    if not table_exists(conn, LAYOUT_BROADCAST_OFF_TABLE):
        raise BroadcastUnavailable("the broadcast table is not present (schema before v37)")
    with transaction(conn):
        row = store._row_for(conn, layout_uuid)
        layout_id = int(row[0])
        target = store._row_id_for_uuid(conn, session_uuid)
        member = conn.execute(
            "SELECT 1 FROM layout_members WHERE layout_id = ? AND session_row_id = ?",
            (layout_id, target)).fetchone()
        if member is None:
            raise store.MemberUnresolved([str(session_uuid)])
        if enabled:
            conn.execute("DELETE FROM layout_broadcast_off WHERE layout_id = ? AND session_row_id = ?",
                         (layout_id, target))
        else:
            conn.execute(
                "INSERT INTO layout_broadcast_off (layout_id, session_row_id, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(layout_id, session_row_id) DO NOTHING",
                (layout_id, target, now or utc_now()))
        conn.execute("UPDATE layouts SET updated_at = ? WHERE id = ?", (now or utc_now(), layout_id))
        return store.WriteResult(layout=store._hydrate(conn, store._row_for(conn, layout_uuid)))


def _live_by_row(infos: Iterable[Any]) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    for info in infos:
        row_id = info.session_row_id
        if isinstance(row_id, int):
            out[row_id] = info
    return out


def _dialog_open(info: Any) -> bool:
    return info.activity_status == STATUS_QUESTION or info.startup_gate == GATE_AWAITING


async def _send_one(member: store.LayoutMember, info: Any, backend: Any, text: str,
                    rewrite: Optional[Callable[[Any, str], str]] = None) -> MemberOutcome:
    def done(status: str, code: Optional[str] = None) -> MemberOutcome:
        return MemberOutcome(member.session_row_id, member.session_uuid, status, code)

    if _dialog_open(info):
        return done(FAILED, "pane_dialog_open")
    try:
        await backend.paste_and_submit(rewrite(info, text) if rewrite else text)
    except PasteNotSettledError:
        return done(FAILED, "paste_not_settled")
    except NotImplementedError:
        return done(FAILED, "paste_unsupported")
    except RuntimeError as exc:
        logger.warning("layout_broadcast_send_failed", session_id=info.session.id,
                       error_type=type(exc).__name__)
        return done(FAILED, "send_failed")
    return done(SENT)


async def broadcast(layout: store.SavedLayout, text: str, *, infos: Iterable[Any],
                    backend_for: Callable[[str], Any],
                    rewrite: Optional[Callable[[Any, str], str]] = None) -> List[MemberOutcome]:
    live = _live_by_row(infos)
    pending: Dict[int, "asyncio.Future[MemberOutcome]"] = {}
    outcomes: List[Optional[MemberOutcome]] = []
    for index, member in enumerate(sorted(layout.members, key=lambda m: m.position)):
        if not member.broadcast:
            outcomes.append(MemberOutcome(member.session_row_id, member.session_uuid, SKIPPED_OFF))
            continue
        info = live.get(member.session_row_id)
        backend = backend_for(info.session.id) if info is not None and info.session else None
        if (info is None or backend is None or info.activity_status == STATUS_DEAD
                or not await asyncio.to_thread(backend.is_alive)):
            outcomes.append(MemberOutcome(member.session_row_id, member.session_uuid, SKIPPED_NOT_LIVE))
            continue
        outcomes.append(None)
        pending[index] = asyncio.ensure_future(_send_one(member, info, backend, text, rewrite))
    for index, future in pending.items():
        outcomes[index] = await future
    final = [o for o in outcomes if o is not None]
    counts: Dict[str, int] = {}
    for outcome in final:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    logger.info("layout_broadcast", layout_uuid=layout.layout_uuid, bytes=len(text.encode("utf-8")),
                members=len(final), **counts)
    return final
