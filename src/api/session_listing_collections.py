
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from src.api import peer_auth
from src.api.session_attach_routes import attachable_rows
from src.api.session_companion_routes import companion_infos
from src.api.session_crud_routes import build_owner_listing
from src.api.session_recent_routes import recent_response
from src.api.session_records_routes import stored_record_rows
from src.api.session_sleep_routes import asleep_record_rows
from src.core.federation import peer_listing
from src.core.listing_push.publisher import Collection, CollectionResult
from src.core.session_sleep import is_asleep, is_closed

LIVE_NAMES = "live_tmux_names"
LIVE_INFOS_KEY = "live_infos"
WAKE_SHARED_KEY = "asleep_wake_shared"


def _failure(exc: HTTPException) -> CollectionResult:
    return CollectionResult(ok=False, status=exc.status_code, detail=exc.detail)


def _names(context: Dict[str, Any]) -> set:
    return context.setdefault(LIVE_NAMES, set())


async def build_list(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    infos = await build_owner_listing(app_state)
    infos = await peer_listing.for_caller(infos, is_peer=False, open_db=peer_auth.open_db)
    rows = [info.model_dump(mode="json") for info in infos]
    _names(context).update(r.get("tmux_session") for r in rows if r.get("tmux_session"))
    context[LIVE_INFOS_KEY] = infos
    return CollectionResult(rows=rows)


async def build_attachable(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    try:
        rows = await asyncio.to_thread(attachable_rows, app_state.session_manager)
    except HTTPException as exc:
        return _failure(exc)
    rows = [dict(row) for row in rows]
    _names(context).update(r.get("name") for r in rows if r.get("name"))
    return CollectionResult(rows=rows)


def running_join_row(row: dict, live_names: set) -> bool:
    if row.get("lifecycle") != "stopped":
        return True
    if is_asleep(row) or is_closed(row):
        return True
    return bool(row.get("tmux_name")) and row.get("tmux_name") in live_names


async def build_records(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    live = set(_names(context))
    try:
        records = await stored_record_rows(app_state, keep=lambda row: running_join_row(row, live), infos=context.get(LIVE_INFOS_KEY),
                                           wake_shared=context.setdefault(WAKE_SHARED_KEY, {}))
    except HTTPException as exc:
        return _failure(exc)
    return CollectionResult(rows=[r.model_dump(mode="json") for r in records])


async def build_asleep(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    try:
        records = await asleep_record_rows(app_state, context.get(LIVE_INFOS_KEY), context.setdefault(WAKE_SHARED_KEY, {}))
    except HTTPException as exc:
        return _failure(exc)
    return CollectionResult(rows=[r.model_dump(mode="json") for r in records])


async def build_companions(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    infos = await companion_infos(app_state)
    return CollectionResult(rows=[info.model_dump(mode="json") for info in infos])


async def build_recent(app_state: Any, context: Dict[str, Any]) -> CollectionResult:
    try:
        body = (await recent_response(app_state)).model_dump(mode="json")
    except HTTPException as exc:
        return _failure(exc)
    rows = body.pop("sessions", []) or []
    return CollectionResult(rows=rows, meta=body)


def _session_id(row: Dict[str, Any]) -> Optional[str]:
    session = row.get("session") or {}
    return session.get("id") if isinstance(session, dict) else None


def listing_collections(app_state: Any) -> List[Collection]:
    def bind(fn):
        async def run(context: Dict[str, Any]) -> CollectionResult:
            return await fn(app_state, context)
        return run

    return [
        Collection("list", bind(build_list), _session_id),
        Collection("attachable", bind(build_attachable), lambda r: r.get("name")),
        Collection("records", bind(build_records), lambda r: r.get("session_uuid")),
        Collection("asleep", bind(build_asleep), lambda r: r.get("session_uuid")),
        Collection("companions", bind(build_companions), _session_id),
        Collection("recent", bind(build_recent), lambda r: r.get("session_uuid")),
    ]
