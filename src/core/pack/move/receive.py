"""The TARGET half of a session move (P5, #165; docs/pack.md 11): check, land, wake, undo. Also a copy and a fresh send (#1653): ``body["mode"]``.

Runs on the machine RECEIVING the session and decides by ITS OWN restrictions, project and logins, never the caller's word. ``dry_run``
answers every refusal and changes nothing (the source asks first, so a refusal happens before anything moves). A real receive files the
conversation under ``ENC(target working dir)`` (in the default Claude projects folder, and in a relay profile's own when the login is relayed) through P4's transcript step, verifies the sha256 of every file, writes the row ASLEEP
(keyed by ``session_uuid``, same conversation id) and wakes it through the one wake (``recreate_by_uuid``, which builds ``--resume <uuid>``
once via ``resume_extra_args``). A failure at any point removes the row it made (or restores the row it changed) and answers a named
refusal; the filed conversation copies stay (identical bytes, harmless). The source is never touched by any of it.
"""

from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

import asyncio
import structlog

from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.pack.identity import home
from src.core.pack.machines import restrictions as restrict
from src.core.pack.migrate import transcripts
from src.core.pack.migrate.manifest import SESSION_COLUMNS
from src.core.pack.migrate.receive import MigrateRefused, TargetEnv, check_allowed
from src.core.pack.move import account, ops
from src.core.pack.transport import blobs
from src.core.trail_entry import utc_now

logger = structlog.get_logger()
SLEPT = "slept_by_user"

Wake = Callable[[str, Optional[str], Dict[str, Any]], Awaitable[Dict[str, Any]]]
LaunchFor = Callable[[Optional[str], str], Optional[Dict[str, Any]]]
ProfileCheck = Callable[[Optional[str]], None]
PROFILE_CODE = "launch_profile_not_on_target"


@dataclass
class MoveTarget:

    env: TargetEnv
    launch_for: LaunchFor
    profile_check: Optional[ProfileCheck] = None


def _working_dir(root: str, rel: str) -> str:
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise MigrateRefused("unsafe_path", "the session's folder is not inside its project", 422)
    return os.path.normpath(os.path.join(root, rel))


def check(target: MoveTarget, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    """Every refusal, in order, changing nothing. Output: {working_dir, project_id, launch, existing}.

    Raises MigrateRefused: ``pack_restricted`` (403), ``project_not_on_target`` (409, with "make a replica" offered),
      ``project_moved_away``, ``working_dir_missing``, ``launch_profile_not_on_target`` (names the profile), ``account_not_usable``, ``session_live_here``,
      ``conversation_already_here`` (another row here already holds that conversation id: a second copy before the first fork's id is learned).
    A copy or a fresh send ADDS an agent, so it is also refused ``pack_restricted`` when ``may_host_agents`` is off or ``max_agents`` is reached.
    """
    check_allowed(target.env, body["project_uid"], None)
    if body.get("mode") in ("copy", "fresh"):
        rule = restrict.check(target.env.restrictions(), restrict.ACTION_HOST_AGENTS, project_uid=body["project_uid"], live_agents=restrict.live_agents())
        if rule is not None:
            raise MigrateRefused("pack_restricted", f"this computer's own restriction {rule} refuses that", 403, rule)
    with closing(target.env.open_db()) as conn:
        project = conn.execute("SELECT * FROM projects WHERE uid = ?", (body["project_uid"],)).fetchone()
        if project is None or project["archived_at"] is not None:
            raise MigrateRefused("project_not_on_target", "this computer does not hold that project yet; make a replica of it here first")
        if project["pack_state"] == home.MOVED_AWAY:
            raise MigrateRefused("project_moved_away", "that project moved away from this computer and cannot start sessions here")
        working_dir = _working_dir(project["root"], body["working_dir_rel"])
        if not os.path.isdir(working_dir):
            raise MigrateRefused("working_dir_missing", "the session's folder is not in this computer's copy of the project yet; sync the project first")
        existing = conn.execute("SELECT * FROM sessions WHERE session_uuid = ?", (body["session_uuid"],)).fetchone()
        if existing is not None and existing["archived_at"] is None and existing["lifecycle"] == "running":
            raise MigrateRefused("session_live_here", "a session with this id is already running here")
        claude_uuid = body["row"].get("claude_session_uuid")
        if body.get("mode") != "fresh" and claude_uuid and conn.execute(
                "SELECT 1 FROM sessions WHERE claude_session_uuid = ? AND session_uuid != ?", (claude_uuid, body["session_uuid"])).fetchone():
            raise MigrateRefused("conversation_already_here", "this computer already holds a session of that conversation; wait for it to learn its own id, or use fresh", 409)
        project_id = project["id"]
    if target.profile_check is not None:
        try:
            target.profile_check(body["row"].get("agent_type"))
        except LaunchProfileNotFound as exc:
            raise MigrateRefused(PROFILE_CODE, f"this computer has no launch profile named {exc.profile_id}; create it here first, then move the session", 409) from exc
    launch = None
    if body.get("agent_family") in (None, "claude"):
        launch = target.launch_for(body.get("account_key"), sender)
        if launch is None:
            raise MigrateRefused(account.NOT_USABLE_CODE, account.NOT_USABLE_DETAIL, 409)
    return {"working_dir": working_dir, "project_id": project_id, "launch": launch or {"account_id": None, "extra_env": None}, "existing": existing}


def _file_conversation(target: MoveTarget, sender: str, body: Mapping[str, Any], seen: Mapping[str, Any]) -> None:
    working_dir = seen["working_dir"]
    try:
        archive = target.env.inbox.sealed_path(body["transcripts_blob_id"], peer=sender)
    except (KeyError, blobs.BlobError) as exc:
        raise MigrateRefused("unknown_blob", "the conversation files did not arrive") from exc
    roots = [target.env.transcripts_root]
    relay = (seen["launch"].get("extra_env") or {}).get("CLAUDE_CONFIG_DIR")
    if relay:
        roots.append(Path(relay) / "projects")
    for root in roots:
        try:
            _written, _same, replaced = transcripts.unpack(str(archive), working_dir, root)
        except transcripts.TranscriptError as exc:
            raise MigrateRefused(exc.code, exc.detail) from exc
        misses = transcripts.verify(body["files"], working_dir, root)
        if misses:
            raise MigrateRefused("verify_failed", "the conversation did not arrive intact: " + ", ".join(misses[:5]))
        transcripts.drop_backups(transcripts.target_folder(working_dir, root), replaced)
    target.env.inbox.remove(body["transcripts_blob_id"])


def land(target: MoveTarget, sender: str, body: Mapping[str, Any], seen: Mapping[str, Any]) -> Dict[str, Any]:
    undo: Dict[str, Any] = {}
    if body.get("mode") != "fresh":
        _file_conversation(target, sender, body, seen)
    if body.get("account_key"):
        target.env.carry_account(body["session_uuid"], body["account_key"])
    stamp = utc_now()
    values = {c: body["row"].get(c) for c in SESSION_COLUMNS if c != "session_uuid"}
    values.update(working_dir=seen["working_dir"], project_id=seen["project_id"], lifecycle="stopped", lifecycle_source=SLEPT, archived_at=None,
                  tmux_name=body["row"].get("tmux_name"), updated_at=stamp)
    with closing(target.env.open_db()) as conn:
        found = seen["existing"]
        if found is None:
            cols = ["session_uuid", *values]
            cur = conn.execute(f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", (body["session_uuid"], *values.values()))
            undo["created_id"] = int(cur.lastrowid)
        else:
            undo["before"] = {"id": found["id"], **{k: found[k] for k in values}}
            conn.execute(f"UPDATE sessions SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), found["id"]))
        conn.commit()
    return undo


def undo_land(target: MoveTarget, undo: Mapping[str, Any]) -> None:
    with closing(target.env.open_db()) as conn:
        if "created_id" in undo:
            conn.execute("DELETE FROM sessions WHERE id = ?", (undo["created_id"],))
        elif "before" in undo:
            before = dict(undo["before"])
            row_id = before.pop("id")
            conn.execute(f"UPDATE sessions SET {', '.join(f'{k} = ?' for k in before)} WHERE id = ?", (*before.values(), row_id))
        conn.commit()


async def receive(target: MoveTarget, sender: str, body: Mapping[str, Any], wake: Wake) -> Dict[str, Any]:
    seen = await asyncio.to_thread(check, target, sender, body)
    if body.get("dry_run"):
        return {"ok": True, "working_dir": seen["working_dir"]}
    op_id, uuid = body["op_id"], body["session_uuid"]

    def record(**kw: Any) -> None:
        with closing(target.env.open_db()) as conn:
            ops.update(conn, op_id, "target", **kw)

    def begin() -> None:
        with closing(target.env.open_db()) as conn:
            ops.create(conn, op_id=op_id, role="target", session_uuid=uuid, claude_session_uuid=body["row"].get("claude_session_uuid"),
                       source_install_id=sender, target_install_id=target.env.install_id, state="moving", step="carry",
                       detail={"mode": body.get("mode", "move")})

    await asyncio.to_thread(begin)
    undo: Optional[Dict[str, Any]] = None
    try:
        undo = await asyncio.to_thread(land, target, sender, body, seen)
        await asyncio.to_thread(record, step="wake")
        mode = body.get("mode", "move")  # conversation id
        answer = await wake(uuid, body["row"].get("agent_type"), {**seen["launch"], "fork": mode == "copy", "fresh": mode == "fresh"})
        if answer.get("status") != "started":
            raise MigrateRefused("wake_refused", str(answer.get("detail") or answer.get("code") or answer.get("status")))
    except MigrateRefused as exc:
        if undo is not None:
            await asyncio.to_thread(undo_land, target, undo)
        await asyncio.to_thread(record, state="failed", error_code=exc.code)
        raise
    except Exception:
        if undo is not None:
            await asyncio.to_thread(undo_land, target, undo)
        await asyncio.to_thread(record, state="failed", error_code="internal")
        raise
    await asyncio.to_thread(record, state="moved", step="forward")
    logger.info("pack_session_received", op_id=op_id)
    return {"moved": True, "working_dir": seen["working_dir"], "status": answer.get("status")}
