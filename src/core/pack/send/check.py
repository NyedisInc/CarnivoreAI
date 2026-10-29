
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from typing import Any, Collection, Dict, Mapping, Optional

from src.core.computers import direction
from src.core.pack.carry import scan, transcript_scan
from src.core.pack.identity import home
from src.core.pack.migrate.plan import MigrateError, Request, SourceEnv, call
from src.core.pack.move import ops, session_move

MODES = session_move.MODES
NOT_THERE = "project_not_on_target"


def _source_reason(subject: Mapping[str, Any]) -> Optional[str]:
    row = subject["row"]
    if not row["claude_session_uuid"]:
        return "no_conversation"
    try:
        session_move.conversation_files(row["working_dir"], row["claude_session_uuid"])
    except MigrateError as exc:
        return exc.code
    return None


def _transcript_part(env: SourceEnv, subject: Mapping[str, Any], carry: "scan.CarrySet", target_install_id: str, can_carry: bool) -> Dict[str, Any]:
    row, project = subject["row"], subject["project"]
    toolchain, others = None, {}
    try:
        with closing(env.open_db()) as conn:
            snap = conn.execute("SELECT last_snapshot_json FROM pack_machines WHERE install_id = ?", (target_install_id,)).fetchone()
            toolchain = (json.loads(snap[0] or "null") or {}).get("toolchain") if snap else None
            others = {r[0]: r[1] for r in conn.execute("SELECT display_name, root FROM projects WHERE id != ? AND archived_at IS NULL", (project["id"],))}
    except (sqlite3.Error, ValueError, AttributeError):
        pass
    path = transcript_scan.transcript_path(row["working_dir"], row["claude_session_uuid"]) if row.get("claude_session_uuid") else None
    found = (transcript_scan.scan_transcript(path, root=project["root"], covered=carry.worktrees, other_projects=others, toolchain=toolchain,
                                             worktrees_of=lambda r: scan.outside_worktrees(r, air_gap=bool(project.get("air_gap"))))
             if path else transcript_scan.TranscriptFindings())
    return found.view(can_carry)


async def _target_reason(request: Request, subject: Mapping[str, Any], account_key: Optional[str], mode: str) -> Optional[str]:
    body = session_move.body_for(subject, ops.new_id(), account_key, dry_run=True, mode=mode, target_uuid=None if mode == "move" else "dry-run-uuid")
    try:
        await call(request, session_move.RECEIVE, body, "check")
    except MigrateError as exc:
        return exc.code
    return None


async def check(env: SourceEnv, request: Request, *, subject: Mapping[str, Any], account_key: Optional[str], target_install_id: str = "",
                target_label: str = "the other computer", target_caps: Collection[str] = ()) -> Dict[str, Any]:
    source = asyncio.to_thread(_source_reason, subject)
    project = subject["project"]
    found = asyncio.to_thread(scan.scan_project, project["root"], air_gap=bool(project.get("air_gap")))
    *reasons, source_reason, carry = await asyncio.gather(*[_target_reason(request, subject, account_key, m) for m in MODES], source, found)
    refusal = scan.blockers(carry, target_label, target_caps)
    out: Dict[str, Any] = {}
    for mode, target in zip(MODES, reasons):
        reason = (None if mode == "fresh" else source_reason) or target
        if refusal is not None and reason in (None, NOT_THERE):
            out[mode] = {"ok": False, "reason": refusal[0], "detail": refusal[1]}
            continue
        out[mode] = {"ok": True} if reason is None else {"ok": False, "reason": reason}
    out["carry"] = carry.view(carries_wip=scan.CARRY_TREE in target_caps)
    out["carry"].update(await asyncio.to_thread(_transcript_part, env, subject, carry, target_install_id, scan.CARRY_TREE in target_caps))
    out["carry"]["total_bytes"] = await asyncio.to_thread(carry.total_bytes, air_gap=bool(project.get("air_gap")))
    for item in out["carry"]["left_behind"]:
        if item["why"] == scan.IGNORED_WHY:
            item["size"] = await asyncio.to_thread(transcript_scan.folder_size, os.path.join(project["root"], item["what"]))
    out["project_on_target"] = NOT_THERE not in reasons and "pack_restricted" not in reasons and not all(r == "machine_unreachable" for r in reasons)
    addable = "pack_restricted" if "pack_restricted" in reasons else None
    addable = addable or (None if subject["project"].get("pack_state") == home.HOME else "not_project_home")
    addable = addable or ("computer_is_one_way" if target_install_id and direction.contained(target_install_id) else None)
    out["project_addable"] = {"ok": True} if addable is None else {"ok": False, "reason": addable}
    return out
