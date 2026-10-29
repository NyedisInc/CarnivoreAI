
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import structlog

from src.core.companion_shell.rows import exclude_clause
from src.core.pack.identity import home, replicas
from src.core.pack.machines import restrictions as restrict
from src.core.pack.migrate import code, manifest as manifest_mod, ops, task_manager_side, transcripts
from src.core.pack.transport import blobs, github_account, ladder
from src.core.pack.trust_carry import store as trust_store
from src.core.pack.transport.tarball import TarballError
from src.core.pack.transport.bundles import BundleError
from src.core.project_colors.legacy_keys import stored_hex
from src.core.project_store import normalize_root
from src.core.project_writes import ProjectRootRefused, refuse_unsafe_root
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

DISK_HEADROOM = 2.0


class MigrateRefused(Exception):

    def __init__(self, code: str, detail: str, status: int = 409, rule: Optional[str] = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status, self.rule = code, detail, status, rule


@dataclass
class TargetEnv:

    open_db: Callable[[], sqlite3.Connection]
    state_dir: str
    inbox: blobs.Inbox
    install_id: str
    restrictions: Callable[[], restrict.Restrictions]
    projects_dir: str
    transcripts_root: Optional[Path] = None
    carry_account: Callable[[str, str], object] = lambda session_uuid, account_key: None


def _safe(name: str) -> str:
    return re.sub(r"[^\w .-]", "_", name).strip(" .") or "project"


def _new_root(env: TargetEnv, body: Mapping[str, Any]) -> str:
    default = os.path.join(env.projects_dir, _safe(body["name"]))
    hint = body.get("root_hint")
    if not hint:
        return default
    base = os.path.realpath(env.projects_dir)
    candidate = normalize_root(hint)
    return candidate if os.path.commonpath([os.path.realpath(candidate), base]) == base else default


def _op_row(conn: sqlite3.Connection, op_id: str) -> Dict[str, Any]:
    row = ops.read(conn, op_id, "target")
    if row is None:
        raise MigrateRefused("unknown_op", "this computer has no such migrate in progress", 404)
    return row


def check_allowed(env: TargetEnv, project_uid: str, company_uid: Optional[str]) -> None:
    r = env.restrictions()
    rule = restrict.check(r, restrict.ACTION_RECEIVE_PROJECTS)
    if rule is None and r.allowed_projects and project_uid not in r.allowed_projects:
        rule = "allowed_projects"
    if rule is None and r.allowed_companies and company_uid and company_uid not in r.allowed_companies:
        rule = "allowed_companies"
    if rule is not None:
        raise MigrateRefused("pack_restricted", f"this computer's own restriction {rule} refuses that", 403, rule)


def prepare(env: TargetEnv, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    check_allowed(env, body["project_uid"], body.get("company_uid"))
    with closing(env.open_db()) as conn:
        existing = conn.execute("SELECT * FROM projects WHERE uid = ?", (body["project_uid"],)).fetchone()
        if existing is None:
            case, root = "new", _new_root(env, body)
            if conn.execute("SELECT 1 FROM projects WHERE display_name = ? AND host_key = 'local'", (body["name"],)).fetchone():
                raise MigrateRefused("project_name_taken", f"a different project here is already named {body['name']!r}")
            if conn.execute("SELECT 1 FROM projects WHERE root = ?", (root,)).fetchone():
                raise MigrateRefused("project_root_in_use", f"the folder {root} already belongs to a project here")
            try:
                refuse_unsafe_root(conn, root)
            except ProjectRootRefused as exc:
                raise MigrateRefused(ProjectRootRefused.CODE, str(exc)) from exc
            if os.path.exists(root) and not (os.path.isdir(root) and not os.listdir(root)):
                raise MigrateRefused("root_not_empty", f"the folder {root} already holds files")
            root_existed = os.path.exists(root)
        elif existing["pack_state"] == home.REPLICA and existing["home_install_id"] == sender:
            case, root, root_existed = "replica", existing["root"], True
        elif existing["pack_state"] == home.MOVED_AWAY and existing["moved_to_install_id"] == sender:
            case, root, root_existed = "return", existing["root"], True
        else:
            raise MigrateRefused("project_uid_conflict", "this computer already holds that project and it is not a copy of the sender's")
        if case != "new" and conn.execute(f"SELECT 1 FROM sessions WHERE project_id = ? AND lifecycle = 'running'{exclude_clause(conn)} LIMIT 1", (existing["id"],)).fetchone():
            raise MigrateRefused("project_live_here", "a session of this project is running here")
        probe = root
        while not os.path.exists(probe) and os.path.dirname(probe) != probe:
            probe = os.path.dirname(probe)
        free = shutil.disk_usage(probe).free
        if free < DISK_HEADROOM * int(body.get("bytes_needed") or 0):
            raise MigrateRefused("not_enough_disk", "this computer does not have room for the project", 507)
        answer = {"root": root, "case": case, "project_id": existing["id"] if existing is not None else None, "free_bytes": free}
        if body.get("dry_run") and body.get("task_file_parts"):
            answer["task_files_not_copied"], failed = task_manager_side.dropped_task_files(env.state_dir, body["task_file_parts"])
            if failed:
                answer["task_files_check_failed"] = True
        if not body.get("dry_run"):
            ops.create(conn, op_id=body["op_id"], kind=body.get("kind", "project"), role="target", subject_uid=body["project_uid"],
                       source_install_id=sender, target_install_id=env.install_id, state="applying", step="prepare",
                       parent_id=body.get("parent_id"), detail={"name": body["name"], "case": case, "root": root, "undo": {},
                              "carry_trust": bool(body.get("source_trusted")) and not root_existed,
                              "carry_imports": bool(body.get("source_imports_ok"))})
    return answer


def _company_login(manifest: Mapping[str, Any]) -> Optional[str]:
    try:
        value = json.loads((manifest.get("company") or {}).get("accounts") or "{}").get("github_login")
    except (TypeError, ValueError, AttributeError):
        return None
    return value if github_account.valid_account(value) else None


def _company_row(conn: sqlite3.Connection, manifest: Mapping[str, Any], undo: Dict[str, Any]) -> Optional[int]:
    company = manifest.get("company")
    if not company:
        return None
    before = conn.execute("SELECT id FROM companies WHERE uid = ?", (company["uid"],)).fetchone() or \
        conn.execute("SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (company["name"],)).fetchone()
    company_id = replicas._ensure_company(conn, company["uid"], company["name"])
    if before is None and company_id is not None:
        undo["company_created"] = company_id
        conn.execute("UPDATE companies SET accounts = ?, hue = ? WHERE id = ?", (company.get("accounts"), company.get("hue"), company_id))
        conn.commit()
    return company_id


def _project_row(conn: sqlite3.Connection, env: TargetEnv, sender: str, op: Mapping[str, Any], manifest: Mapping[str, Any],
                 company_id: Optional[int], undo: Dict[str, Any]) -> int:
    from src.core.project_writes import create_project

    p = manifest["project"]
    if op["detail"]["case"] == "new":
        row = create_project(conn, name=p["display_name"], path=op["detail"]["root"], description=p.get("description"), agent_type=p.get("default_agent_type"))
        undo["project_created"] = row["id"]
        project_id = row["id"]
    else:
        existing = conn.execute("SELECT id, pack_state, home_install_id, moved_to_install_id FROM projects WHERE uid = ?", (p["uid"],)).fetchone()
        undo["project_before"] = {k: existing[k] for k in ("pack_state", "home_install_id", "moved_to_install_id")}
        project_id = existing["id"]
    conn.execute(
        "UPDATE projects SET uid = ?, pack_state = 'replica', home_install_id = ?, moved_to_install_id = NULL, company_id = COALESCE(?, company_id), "
        "short_description = COALESCE(?, short_description), color = COALESCE(?, color), air_gap = ?, github_account = COALESCE(?, github_account), "
        "updated_at = ? WHERE id = ?",
        (p["uid"], sender, company_id, p.get("short_description"), stored_hex(p.get("color")), int(bool(p.get("air_gap"))), p.get("github_account"), utc_now(), project_id))
    conn.commit()
    return project_id


def receive(env: TargetEnv, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    op_id, undo, project_id, root = body["op_id"], {}, None, None
    try:
        with closing(env.open_db()) as conn:
            op = _op_row(conn, op_id)
            root = op["detail"]["root"]
            path = env.inbox.sealed_path(body["manifest_blob_id"], peer=sender)
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))
            ops.update(conn, op_id, "target", step="code")
            company_id = _company_row(conn, manifest, undo)
            meta = dict(body.get("code") or {})
            archive = str(env.inbox.sealed_path(meta["blob_id"], peer=sender)) if meta.get("blob_id") else None
            login = None
            if body["rung"] == ladder.RUNG_GIT:
                login = github_account.resolve(air_gap=bool(body.get("air_gap")), project_account=manifest["project"].get("github_account"),
                                               company_account=_company_login(manifest), origin_url=meta.get("remote")).account
            code.bring(body["rung"], root, undo, sender=sender, meta=meta, archive=archive, air_gap=bool(body.get("air_gap")), github_login=login)
            ops.update(conn, op_id, "target", step="rows", detail={"undo": undo})
            project_id = _project_row(conn, env, sender, op, manifest, company_id, undo)
            if op["detail"].get("carry_trust") and op["detail"]["case"] == "new" and undo.get("root_created") and not undo.get("aside") and trust_store.record(
                    conn, root, manifest["project"]["uid"], sender, op_id, projects_dir=env.projects_dir,
                    imports_ok=bool(op["detail"].get("carry_imports"))):
                undo["trust_op"] = op_id
            summary = manifest_mod.apply(conn, manifest, project_id=project_id, target_root=root, state_dir=env.state_dir, undo=undo)
            for s in manifest["sessions"]:
                if s.get("account_key"):
                    env.carry_account(s["session_uuid"], s["account_key"])
            ops.update(conn, op_id, "target", step="transcripts", detail={"undo": undo, "project_id": project_id})
            written: list = []
            if body.get("transcripts_blob_id"):
                written, _same, replaced = transcripts.unpack(str(env.inbox.sealed_path(body["transcripts_blob_id"], peer=sender)), root, env.transcripts_root)
                undo["transcripts"] = written
                undo["transcripts_replaced"] = replaced
            ops.update(conn, op_id, "target", state="verifying", step="verify", detail={"undo": undo, "project_id": project_id, "rung": body["rung"], "code": meta,
                                                                                       "manifest_blob": body["manifest_blob_id"], "transcripts_blob": body.get("transcripts_blob_id")})
            home.notify_changed()
            return {"summary": summary, "written": len(written), "root": root}
    except (code.CodeError, manifest_mod.ManifestError, transcripts.TranscriptError, BundleError, TarballError, blobs.BlobError) as exc:
        _rollback(env, op_id, undo, project_id, root)
        raise MigrateRefused(getattr(exc, "code", "receive_failed"), str(exc)) from exc
    except ladder.AirGapViolation as exc:
        _rollback(env, op_id, undo, project_id, root)
        raise MigrateRefused("air_gap", str(exc)) from exc
    except ProjectRootRefused as exc:
        _rollback(env, op_id, undo, project_id, root)
        raise MigrateRefused(ProjectRootRefused.CODE, str(exc)) from exc
    except Exception:
        _rollback(env, op_id, undo, project_id, root)
        raise


def _rollback(env: TargetEnv, op_id: str, undo: Dict[str, Any], project_id: Optional[int], root: Optional[str]) -> None:
    with closing(env.open_db()) as conn:
        _undo_all(env, conn, undo, project_id, root)
        ops.update(conn, op_id, "target", state="failed", step="abort", detail={"undo": {}})


def _undo_all(env: TargetEnv, conn: sqlite3.Connection, undo: Mapping[str, Any], project_id: Optional[int], root: Optional[str]) -> None:
    if undo.get("transcripts") and root:
        folder = transcripts.target_folder(root, env.transcripts_root)
        for rel in undo["transcripts"]:
            (folder / rel).unlink(missing_ok=True)
    if undo.get("transcripts_replaced") and root:
        transcripts.restore_replaced(transcripts.target_folder(root, env.transcripts_root), undo["transcripts_replaced"])
    if undo.get("trust_op"):
        trust_store.forget_op(conn, undo["trust_op"])
    manifest_mod.undo_rows(conn, undo, target_root=root, project_id=project_id, state_dir=env.state_dir)
    if undo.get("project_created"):
        conn.execute("DELETE FROM projects WHERE id = ?", (undo["project_created"],))
        conn.commit()
    elif undo.get("project_before") and project_id is not None:
        b = undo["project_before"]
        conn.execute("UPDATE projects SET pack_state = ?, home_install_id = ?, moved_to_install_id = ? WHERE id = ?",
                     (b["pack_state"], b["home_install_id"], b["moved_to_install_id"], project_id))
        conn.commit()
    if undo.get("company_created"):
        conn.execute("DELETE FROM companies WHERE id = ? AND NOT EXISTS (SELECT 1 FROM projects WHERE company_id = companies.id)", (undo["company_created"],))
        conn.commit()
    code.undo_code(undo, root)
    home.notify_changed()


def abort(env: TargetEnv, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    with closing(env.open_db()) as conn:
        row = ops.read(conn, body["op_id"], "target")
        if row is None or row["source_install_id"] != sender:
            return {"aborted": False}
        if row["state"] == "flipped":
            raise MigrateRefused("already_flipped", "this computer already took the project; move it back instead")
        d = row["detail"]
        _undo_all(env, conn, d.get("undo") or {}, d.get("project_id"), d.get("root"))
        ops.update(conn, body["op_id"], "target", state="failed", step="abort", error_code="aborted", detail={"undo": {}})
    for key in ("manifest_blob", "transcripts_blob"):
        if d.get(key):
            env.inbox.remove(d[key])
    if (d.get("code") or {}).get("blob_id"):
        env.inbox.remove(d["code"]["blob_id"])
    return {"aborted": True}


def verify(env: TargetEnv, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    with closing(env.open_db()) as conn:
        row = _op_row(conn, body["op_id"])
        d = row["detail"]
        manifest = json.loads(Path(env.inbox.sealed_path(d["manifest_blob"], peer=sender)).read_text(encoding="utf-8"))
        misses = []
        project = conn.execute("SELECT * FROM projects WHERE uid = ?", (row["subject_uid"],)).fetchone()
        if project is None or project["pack_state"] != home.REPLICA:
            return {"ok": False, "misses": ["project_row"]}
        for s in manifest["sessions"]:
            if conn.execute("SELECT 1 FROM sessions WHERE session_uuid = ? AND project_id = ?", (s["session_uuid"], project["id"])).fetchone() is None:
                misses.append("session")
        for a in manifest["agents"]:
            found = conn.execute("SELECT state FROM swarm_agents WHERE thread_key = ? AND project_id = ? AND torn_down_at IS NULL", (manifest_mod.thread_key_here(a, project["id"]), project["id"])).fetchone()
            if found is None or found[0] != "asleep":
                misses.append("agent")
        from src.core.pack.migrate import task_manager_side

        want = {"items": len(manifest["huddle"]["items"]), "messages": len(manifest["huddle"]["messages"]), "groups": len(manifest["huddle"]["groups"])}
        if task_manager_side.counts(env.state_dir, str(project["id"])) != want:
            misses.append("huddle")
        misses += ["transcript"] * len(transcripts.verify(manifest.get("transcripts", []), project["root"], env.transcripts_root))
        misses += code.check(d["rung"], project["root"], d["code"], air_gap=bool(manifest["project"].get("air_gap")))
        ops.update(conn, body["op_id"], "target", step="flip" if not misses else "verify")
    return {"ok": not misses, "misses": sorted(set(misses))}


def flip(env: TargetEnv, sender: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    with closing(env.open_db()) as conn:
        row = _op_row(conn, body["op_id"])
        if row["state"] == "flipped":
            return {"flipped": True, "root": row["detail"]["root"], "reinstall_failed": []}
        if row["state"] != "verifying":
            raise MigrateRefused("not_verified", "the op was not verified on this computer", 409)
        project = conn.execute("SELECT id FROM projects WHERE uid = ?", (row["subject_uid"],)).fetchone()
        home.set_state(conn, project["id"], home.HOME)
        d = row["detail"]
        ops.update(conn, body["op_id"], "target", state="flipped", step="flip", detail={"undo": {}})
    for key in ("manifest_blob", "transcripts_blob"):
        if d.get(key):
            env.inbox.remove(d[key])
    if (d.get("code") or {}).get("blob_id"):
        env.inbox.remove(d["code"]["blob_id"])
    if (d.get("undo") or {}).get("transcripts_replaced"):
        transcripts.drop_backups(transcripts.target_folder(d["root"], env.transcripts_root), d["undo"]["transcripts_replaced"])
    failed = code.reinstall(d["root"]) if d.get("rung") == ladder.RUNG_TAR else []
    return {"flipped": True, "root": d["root"], "reinstall_failed": failed}
