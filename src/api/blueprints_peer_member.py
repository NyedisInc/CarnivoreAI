
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

from src.api import peer_auth, peer_route_guard
from src.api.blueprints_launch import StepFailed
from src.core.federation import peer_forward
from src.models.blueprints import BlueprintSession
from src.models.blueprints_launch import LaunchedSession

SHADOW_WAIT_SECONDS = 8.0
_POLL = 0.5


def check_supported(member: BlueprintSession) -> None:
    if member.folder.mode != "existing":
        raise StepFailed("folder", "peer_worktree_unsupported",
                         "a worktree is made by the computer that owns the repository; use an existing folder on that computer")
    if member.skills:
        raise StepFailed("skills", "peer_skills_unsupported",
                         "skills install from this computer's catalog only; leave the skills off a member on another computer")


def _target(host_key: str) -> Any:
    with closing(peer_auth.open_db()) as conn:
        return peer_forward.create_peer(conn, host_key)


def _shadow_row(host_key: str, name: str) -> Tuple[Optional[int], Optional[str]]:
    with closing(peer_auth.open_db()) as conn:
        row = conn.execute("SELECT s.id, s.session_uuid FROM peer_sessions ps JOIN sessions s ON s.id = ps.session_id "
                           "WHERE ps.host_key = ? AND ps.peer_name = ?", (host_key, name)).fetchone()
    return (int(row[0]), str(row[1])) if row else (None, None)


async def peer_problem(host_key: str) -> list:
    from src.core.federation import peer_links
    from src.models.blueprints_launch import Problem

    peer = await asyncio.to_thread(_target, host_key)
    if peer is None:
        return [Problem(step="session", code="peer_unknown", detail=f"{host_key} is not a paired computer")]
    links = peer_links.LINKS
    if links is None or links.client(peer.peer_install_id) is None:
        return [Problem(step="session", code="peer_unavailable", detail=f"{peer.label} is not connected")]
    return []


async def create_peer_member(member: BlueprintSession, cols: Optional[int], rows: Optional[int]) -> LaunchedSession:
    check_supported(member)
    host_key = member.host_key or ""
    peer = await asyncio.to_thread(_target, host_key)
    if peer is None:
        raise StepFailed("session", "peer_unknown", f"{host_key} is not a paired computer")
    from src.core.session_name_claim import sanitize_tmux_name

    body: Dict[str, Any] = {
        "working_dir": member.folder.path, "project_name": sanitize_tmux_name(member.label), "label": member.label,
        "agent_type": member.family, "model": member.model, "opening_prompt": member.opening_prompt,
        "cols": cols, "rows": rows}
    rule = peer_forward.rule_for("POST", "/api/v1/sessions")
    path, sent = peer_forward.build_request(rule, "local", {}, [], {k: v for k, v in body.items() if v is not None})
    try:
        answer = await peer_route_guard.forward_reply(rule, peer, path, sent)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise StepFailed("session", str(detail.get("code", f"create_{exc.status_code}")),
                         str(detail.get("detail", exc.detail))) from None
    try:
        created = json.loads(answer.body)
    except ValueError:
        created = {}
    if answer.status_code != 201 or not isinstance(created.get("id"), str):
        raise StepFailed("session", f"create_{answer.status_code}", _owner_reason(created))
    wire = created["id"]
    name = wire.rsplit(":", 1)[-1]
    row_id, session_uuid = None, None
    for _ in range(int(SHADOW_WAIT_SECONDS / _POLL)):
        row_id, session_uuid = await asyncio.to_thread(_shadow_row, peer.key, name)
        if row_id is not None:
            break
        await asyncio.sleep(_POLL)
    return LaunchedSession(id=wire, tmux_session=name, session_row_id=row_id, session_uuid=session_uuid)


def _owner_reason(created: Any) -> str:
    detail = created.get("detail") if isinstance(created, dict) else None
    return str(detail if detail else "the other computer refused the session")[:300]
