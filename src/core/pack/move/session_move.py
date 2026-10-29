
from __future__ import annotations

import asyncio
import os
import shutil
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.pack.identity import home
from src.core.pack.migrate import transcripts
from src.core.pack.migrate.manifest import SESSION_COLUMNS
from src.core.pack.migrate.plan import MigrateError, Request, SourceEnv, call
from src.core.pack.move import inflight
from src.core.pack.carry.step import CodeStep
from src.core.pack.move import interrupt as interrupt_mod, moved_note, ops, turn
from src.core.pack.send import snapshot
from src.core.pack.transport import blobs
from src.core.session_sleep import is_asleep

logger = structlog.get_logger()
RECEIVE = "/federation/pack/session/receive"
DEFAULT_WAIT_SECONDS = 600
MODES = ("move", "copy", "fresh")


@dataclass
class Hooks:

    find: Callable[[str], Awaitable[Any]]
    sleep: Callable[[str], Awaitable[None]]
    wake: Callable[[str], Awaitable[None]]
    hide: Callable[[str], Awaitable[None]]
    account_key: Callable[[str], Optional[str]]
    background_members: Optional[Callable[[str], Awaitable[List[Tuple[int, str]]]]] = None
    stop_members: Optional[Callable[[str, List[Tuple[int, str]]], Awaitable[List[int]]]] = None
    interrupt: Optional[Callable[[str], Awaitable[None]]] = None
    profile_root: Optional[Callable[[str], Optional[Path]]] = None


def read_subject(conn: Any, session_uuid: str, *, need_conversation: bool = True) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM sessions WHERE session_uuid = ? AND archived_at IS NULL", (session_uuid,)).fetchone()
    if row is None:
        raise MigrateError("unknown_session", "no such session here", 404)
    row = dict(row)
    if row["project_id"] is None or row["working_dir"] is None:
        raise MigrateError("session_not_movable", "only a session that belongs to a project can move", 409)
    if need_conversation and not row["claude_session_uuid"]:
        raise MigrateError("no_conversation", "the session has no conversation to resume yet; let it finish a first turn", 409)
    project = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (row["project_id"],)).fetchone())
    if project.get("pack_state") == home.MOVED_AWAY:
        raise MigrateError("project_moved_away", "the session's project moved away from this computer", 409)
    rel = os.path.relpath(row["working_dir"], project["root"])
    if rel.startswith(".."):
        raise MigrateError("session_outside_project", "the session runs outside its project's folder", 409)
    return {"row": row, "project": project, "working_dir_rel": rel}


def conversation_files(working_dir: str, claude_uuid: str, *, with_memory: bool = False, prefer_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    files = [f for f in transcripts.source_files(working_dir, prefer_root=prefer_root)
             if f["rel"] == f"{claude_uuid}.jsonl" or f["rel"].startswith(f"{claude_uuid}/") or (with_memory and f["rel"].startswith(moved_note.MEMORY_PREFIX))]
    if not any(f["rel"] == f"{claude_uuid}.jsonl" for f in files):
        raise MigrateError("no_conversation_file", "this computer holds no transcript for the session's conversation, so it could not resume elsewhere", 409)
    return files


def _plain(exc: HTTPException) -> str:
    detail = exc.detail
    return str((detail.get("message") or detail.get("detail")) if isinstance(detail, dict) else detail)[:200]


def turn_ended_text(exc: "turn.TurnNotEnded", name: str) -> str:
    if exc.hint is not None and exc.state in turn.RESTING:
        count = exc.background
        if isinstance(count, int) and count > 0:
            return f"{name} still has {count} background {'shell' if count == 1 else 'shells'} running; stop {'it' if count == 1 else 'them'}, then send again"
        return f"{name} still has a background task running; wait for it to finish or stop it, then send again"
    if exc.state is None:
        return f"{name} was not listed for the whole wait; check that it is running, then send again"
    if exc.state == "question":
        return f"{name} is waiting for your answer; answer it, then send again"
    if exc.state in turn.RESTING:
        return f"{name} is still starting up or waiting on a dialog; answer it, then send again"
    return f"{name} was still working when the wait ended; a running turn is never stopped, so send again when its turn is over"


def body_for(subject: Mapping[str, Any], op_id: str, account_key: Optional[str], *, dry_run: bool, mode: str = "move", target_uuid: Optional[str] = None) -> Dict[str, Any]:
    row = subject["row"]
    wire = {c: row[c] for c in SESSION_COLUMNS}
    wire["tmux_name"] = row["tmux_name"]
    if mode == "fresh":
        wire.update(claude_session_uuid=None, claude_session_uuid_source=None)
    body = {"op_id": op_id, "dry_run": dry_run, "session_uuid": target_uuid or row["session_uuid"], "project_uid": subject["project"]["uid"],
            "working_dir_rel": subject["working_dir_rel"], "agent_family": row["agent_family"], "account_key": account_key, "row": wire}
    return {**body, "mode": mode} if mode != "move" else body


async def _db(env: SourceEnv, fn: Callable[[Any], Any]) -> Any:
    def run() -> Any:
        with closing(env.open_db()) as conn:
            return fn(conn)
    return await asyncio.to_thread(run)


async def move_session(env: SourceEnv, hooks: Hooks, request: Request, *, subject: Mapping[str, Any], target_install_id: str, target_label: str,
                       op_id: Optional[str] = None, wait_seconds: float = DEFAULT_WAIT_SECONDS, mode: str = "move",
                       add_project: Optional[Callable[[], Awaitable[None]]] = None, stop_running: bool = False,
                       code: Optional[CodeStep] = None) -> Dict[str, Any]:
    row, op_id = subject["row"], op_id or ops.new_id()
    uuid, claude_uuid = row["session_uuid"], row["claude_session_uuid"]
    target_uuid = uuid if mode == "move" else str(uuid_lib.uuid4())
    await _db(env, lambda c: ops.create(c, op_id=op_id, role="source", session_uuid=uuid, claude_session_uuid=claude_uuid, source_install_id=env.install_id,
                                        target_install_id=target_install_id, detail={"machine": target_label, "name": row.get("title"), "mode": mode,
                                                                                    "target_session_uuid": target_uuid}))
    step, slept, interrupted, target_dir = "check", False, False, None

    async def at(name: str) -> None:
        nonlocal step
        step = name
        await _db(env, lambda c: ops.update(c, op_id, "source", step=name))

    agent_name = str(row.get("title") or "the agent")

    async def note_blocker(text: str) -> None:
        await _db(env, lambda c: ops.update(c, op_id, "source", detail={"waiting_on": text}))

    work = os.path.join(env.outbox, op_id)

    def note_args() -> Tuple[str, str]:
        left = code.found.view()["left_behind"] if code is not None and code.found is not None else []
        moved = code.moved if code is not None else {}
        return (moved_note.note_text(target_label, row["working_dir"], target_dir, left, moved), moved_note.paste_text(target_label, row["working_dir"], target_dir, left, moved))

    try:
        account_key = await asyncio.to_thread(hooks.account_key, uuid)
        if mode != "fresh":
            await asyncio.to_thread(conversation_files, row["working_dir"], claude_uuid)
        if code is not None:
            await code.gate()
        dry = body_for(subject, op_id, account_key, dry_run=True, mode=mode, target_uuid=target_uuid)
        need_project = False
        try:
            target_dir = (await call(request, RECEIVE, dry, "check")).get("working_dir")
        except MigrateError as exc:
            if exc.code != "project_not_on_target" or add_project is None:
                raise
            need_project = True
        body = body_for(subject, op_id, account_key, dry_run=False, mode=mode, target_uuid=target_uuid)
        resting = is_asleep(row)
        if mode != "fresh" and not resting:
            if stop_running and mode == "move" and hooks.interrupt is not None and interrupt_mod.is_running(await hooks.find(uuid)):
                await at("interrupt")
                await _db(env, lambda c: ops.update(c, op_id, "source", detail={"agents": 1}))
                try:
                    await hooks.interrupt(uuid)
                except HTTPException as exc:
                    raise MigrateError("interrupt_failed", f"{agent_name} could not be interrupted: {_plain(exc)}", 409, "interrupt") from exc
                interrupted = True
            await at("wait")
            until = (datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
            await _db(env, lambda c: ops.update(c, op_id, "source", detail={"wait_until": until}))
            try:
                await turn.wait_for_turn_end(lambda: hooks.find(uuid), wait_seconds, name=agent_name, on_blocker=note_blocker, shells_ok=True)
            except turn.TurnNotEnded as exc:
                raise MigrateError("turn_not_ended", turn_ended_text(exc, agent_name), 409, "wait") from exc
        if need_project:
            await at("project")
            inflight.lock(op_id, "project")
            await add_project()
            inflight.unlock(op_id, "project")
            await at("check")
            target_dir = (await call(request, RECEIVE, dry, "check")).get("working_dir")
        if code is not None:
            await at("code")
            await code.carry()
        if mode != "fresh":
            if mode == "move" and not resting:
                shells = turn.shells_only(await hooks.find(uuid)) if hooks.background_members is not None else 0
                members: List[Tuple[int, str]] = []
                if shells:
                    try:
                        members = await hooks.background_members(uuid)
                    except HTTPException as exc:
                        raise MigrateError("shells_not_stopped", _plain(exc), 409, "sleep") from exc
                await at("sleep")
                slept = True
                try:
                    await hooks.sleep(uuid)
                except HTTPException as exc:
                    slept = False
                    raise MigrateError("sleep_refused", str(exc.detail)[:200], 409, "sleep") from exc
                if members:
                    await at("stop_shells")
                    await _db(env, lambda c: ops.update(c, op_id, "source", detail={"shells": shells}))
                    try:
                        await hooks.stop_members(uuid, members)
                    except HTTPException as exc:
                        raise MigrateError("shells_not_stopped", _plain(exc), 409, "stop_shells") from exc
            await at("carry")
            first = await _db(env, lambda c: moved_note.first_to_target(c, subject["project"]["id"], target_install_id, op_id))
            files = await asyncio.to_thread(lambda: conversation_files(row["working_dir"], claude_uuid, with_memory=first,
                                                                       prefer_root=hooks.profile_root(uuid) if hooks.profile_root else None))
            os.makedirs(work, mode=0o700, exist_ok=True)
            if mode == "copy":
                files = await asyncio.to_thread(snapshot.whole_lines, files, os.path.join(work, "snapshot"))
            if mode == "move":
                files = await asyncio.to_thread(moved_note.add_note, files, os.path.join(work, "note"), op_id, target_label, note_args()[0])
            path = os.path.join(work, "session.tar.gz")
            await asyncio.to_thread(transcripts.build_archive, files, path)
            try:
                blob = await blobs.send_file(request, path, blob_id=blobs.new_id(), kind="transcripts")
            except blobs.BlobError as exc:
                raise MigrateError(exc.code, "the other computer refused the conversation files", 502, "carry") from exc
            body.update(transcripts_blob_id=blob, files=[{"rel": f["rel"], "sha256": f["sha256"]} for f in files])
        inflight.lock(op_id, "wake")
        await at("wake")
        answer = await call(request, RECEIVE, body, "wake")
        if mode == "move":
            await at("forward")
            await hooks.hide(uuid)
        told: Dict[str, Any] = {}
        if interrupted:
            await at("continue")
            await _db(env, lambda c: ops.update(c, op_id, "source", detail={"agents": 1}))
            told = await interrupt_mod.tell_continue(request, [(uuid, agent_name)], extra=note_args()[1])
        await _db(env, lambda c: ops.update(c, op_id, "source", state="moved", step="forward" if mode == "move" else "wake",
                                            detail={"machine": target_label, "working_dir": answer.get("working_dir"), **told}))
        logger.info("pack_session_sent", op_id=op_id, machine=target_label, mode=mode)
        return {"op_id": op_id, "machine": target_label, "session_uuid": uuid, "target_session_uuid": target_uuid}
    except asyncio.CancelledError:
        if slept:
            try:
                await hooks.wake(uuid)
            except HTTPException as wake_exc:
                logger.warning("pack_session_move_rewake_failed", op_id=op_id, status=wake_exc.status_code)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=step, error_code="cancelled"))
        logger.info("pack_session_send_cancelled", op_id=op_id, step=step)
        raise
    except MigrateError as exc:
        if slept and exc.code != "machine_unreachable":
            try:
                await hooks.wake(uuid)
            except HTTPException as wake_exc:
                logger.warning("pack_session_move_rewake_failed", op_id=op_id, status=wake_exc.status_code)
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=exc.step or step, error_code=exc.code, detail={"error": exc.detail}))
        exc.step = exc.step or step
        raise
    except Exception:
        await _db(env, lambda c: ops.update(c, op_id, "source", state="failed", step=step, error_code="internal"))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
