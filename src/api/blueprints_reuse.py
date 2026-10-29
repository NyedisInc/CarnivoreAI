
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import Request

from src.config import settings
from src.core.db import connect, db_path_for
from src.models.blueprints import BlueprintSession
from src.models.blueprints_launch import LaunchedSession


class LiveSessions:

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows = rows
        self.claimed: Set[int] = set()

    def match(self, member: BlueprintSession) -> Optional[Tuple[LaunchedSession, bool]]:
        if member.host_key:
            return None
        free = [r for r in self.rows if r["row_id"] not in self.claimed]
        found: List[Dict[str, Any]] = []
        if member.session_uuid:
            found = [r for r in free if r["session_uuid"] == member.session_uuid]
        elif member.folder.mode == "existing":
            want = os.path.realpath(member.folder.path)
            label = member.label.casefold()
            found = [r for r in free if r["label"].casefold() == label and r["folder"] == want]
        found = [r for r in found if not r["asleep"]] or found
        if len(found) != 1:
            return None
        row = found[0]
        self.claimed.add(row["row_id"])
        return (LaunchedSession(id=row["id"], tmux_session=row["tmux_session"],
                                session_row_id=row["row_id"], session_uuid=row["session_uuid"]),
                row["asleep"])


def _uuids(row_ids: List[int]) -> Dict[int, str]:
    if not row_ids:
        return {}
    marks = ",".join("?" * len(row_ids))
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        found = conn.execute(f"SELECT id, session_uuid FROM sessions WHERE id IN ({marks})",
                             row_ids).fetchall()
    return {int(r[0]): str(r[1]) for r in found if r[1]}


def _asleep_rows() -> List[Dict[str, Any]]:
    from src.core import session_sleep

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        found = session_sleep.asleep_rows(conn)
    return [{
        "row_id": int(r["id"]), "session_uuid": str(r["session_uuid"]), "id": str(r["session_uuid"]),
        "tmux_session": r.get("tmux_name"), "asleep": True,
        "label": str(r.get("title") or r.get("tmux_name") or "").strip(),
        "folder": os.path.realpath(r["working_dir"])} for r in found
        if r.get("session_uuid") and r.get("working_dir")]


async def live_sessions(request: Request) -> LiveSessions:
    infos = await request.app.state.session_manager.list_session_infos()
    infos = [i for i in infos if i.session_row_id is not None]
    uuids = await asyncio.to_thread(_uuids, [int(i.session_row_id) for i in infos])
    rows: List[Dict[str, Any]] = []
    for info in infos:
        row_id = int(info.session_row_id)
        if row_id not in uuids:
            continue
        rows.append({
            "row_id": row_id, "session_uuid": uuids[row_id], "id": info.session.id,
            "tmux_session": info.tmux_session, "asleep": False,
            "label": (info.label or info.tmux_session or "").strip(),
            "folder": os.path.realpath(info.session.working_dir)})
    live_ids = {r["row_id"] for r in rows}
    rows.extend(r for r in await asyncio.to_thread(_asleep_rows) if r["row_id"] not in live_ids)
    return LiveSessions(rows)


async def wake_member(request: Request, session: LaunchedSession) -> LaunchedSession:
    from fastapi import HTTPException

    from src.api import session_sleep_routes
    from src.api.blueprints_launch import StepFailed
    from src.api.error_response import sentence_of

    try:
        result = await session_sleep_routes.wake_session(request, str(session.session_uuid), None)
    except HTTPException as exc:
        raise StepFailed("session", f"wake_{exc.status_code}", sentence_of(exc.detail)) from None
    if result.status != "started":
        raise StepFailed("session", result.code or "wake_refused",
                         result.detail or "the asleep session could not be woken")
    return LaunchedSession(id=result.session_id or session.id,
                           tmux_session=result.tmux_session or session.tmux_session,
                           session_row_id=session.session_row_id, session_uuid=session.session_uuid)
