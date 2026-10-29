
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Collection, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.companion_shell.rows import exclude_clause
from src.core.pack.carry import scan
from src.core.pack.identity import home
from src.core.pack.migrate import code, live_agents, manifest as manifest_mod, ops, task_manager_side, transcripts
from src.core.pack.transport import blobs, github_account, ladder, publish

logger = structlog.get_logger()
Request = Callable[..., Awaitable[Tuple[int, Any]]]
PREPARE, RECEIVE, VERIFY, FLIP, ABORT = (f"/federation/pack/migrate/{n}" for n in ("prepare", "receive", "verify", "flip", "abort"))


class MigrateError(Exception):

    def __init__(self, code: str, detail: str, status: int = 409, step: Optional[str] = None, rule: Optional[str] = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status, self.step, self.rule = code, detail, status, step, rule


@dataclass
class SourceEnv:

    open_db: Callable[[], sqlite3.Connection]
    state_dir: str
    install_id: str
    outbox: str
    label_of: Callable[[str], str] = lambda install_id: install_id
    account_of: Callable[[str], Optional[str]] = lambda session_uuid: None
    profile_of: Callable[[str], Optional[str]] = lambda session_uuid: None
    find_live: Optional[Callable[[str], Awaitable[Any]]] = None


@dataclass
class Plan:

    project: Dict[str, Any]
    target_install_id: str
    target_label: str
    target_root: str
    case: str
    rung: str
    reason: str
    one_way: bool
    code_meta: Dict[str, Any]
    checks: List[Dict[str, Any]]
    summary: Dict[str, Any]
    manifest: Dict[str, Any] = field(repr=False)
    files: List[Dict[str, Any]] = field(repr=False)
    publish_card: Optional[Dict[str, Any]] = None
    fingerprint: str = ""
    target_caps: Tuple[str, ...] = ()
    carry: Optional[scan.CarrySet] = field(default=None, repr=False)

    @property
    def blocking(self) -> List[str]:
        return [c["name"] for c in self.checks if not c["ok"] and c.get("blocking", True)]

    def view(self) -> Dict[str, Any]:
        return {"project": self.project["display_name"], "project_uid": self.project["uid"], "kind": "project", "machine": self.target_label,
                "target_install_id": self.target_install_id, "source_root": self.project["root"], "target_root": self.target_root, "case": self.case,
                "rung": self.rung, "rung_reason": self.reason, "one_way": self.one_way, "air_gap": bool(self.project.get("air_gap")),
                "checks": self.checks, "blocking": self.blocking, "can_apply": not self.blocking, "summary": self.summary,
                "publish_card": self.publish_card, "plan_fingerprint": self.fingerprint}


async def call(request: Request, path: str, body: Mapping[str, Any], step: str) -> Dict[str, Any]:
    status, answer = await request("POST", path, json=dict(body))
    if status == 200 and isinstance(answer, dict):
        return answer
    detail = answer.get("detail") if isinstance(answer, dict) else None
    code_ = detail.get("code") if isinstance(detail, dict) else None
    text = detail.get("detail") if isinstance(detail, dict) else None
    raise MigrateError(code_ or "target_refused", text or f"the other computer refused ({status})", 403 if code_ == "pack_restricted" else 502 if status >= 500 or status == 0 else 409,
                       step, detail.get("rule") if isinstance(detail, dict) else None)


def _company(conn: sqlite3.Connection, project: Mapping[str, Any]) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM companies WHERE id = ?", (project["company_id"],)).fetchone() if project.get("company_id") is not None else None


def _owner_pointer(company: Optional[sqlite3.Row], key: str) -> Optional[str]:
    try:
        return json.loads(company["accounts"] or "{}").get(key) if company is not None else None
    except (TypeError, ValueError):
        return None


def _check(name: str, ok: bool, detail: str, blocking: bool = True) -> Dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "blocking": blocking}


def choose(project: Mapping[str, Any], described: Mapping[str, Any], override: Optional[str]) -> ladder.Choice:
    air_gap = bool(project.get("air_gap"))
    has_git = bool(described["is_repo"] and described["has_commits"])
    chosen = ladder.choose_rung(purpose=ladder.PURPOSE_MOVE, air_gap=air_gap, has_git=has_git, has_remote=bool(described["remote"]))
    if chosen.rung == ladder.RUNG_GIT and not described["pushed"]:
        chosen = ladder.Choice(ladder.RUNG_CARRIED, "the project has a remote but its newest commits are not on it, so carnivore carries them over the link")
    if override and override != chosen.rung:
        if override == ladder.RUNG_CARRIED and has_git:
            return ladder.Choice(ladder.RUNG_CARRIED, "you chose to send the commits over the link")
        if override == ladder.RUNG_TAR and has_git:
            raise MigrateError("rung_unavailable", "a project with git history goes over the link or by its remote, never as an archive (the archive leaves .git behind)", 422)
        if override == ladder.RUNG_TAR:
            return ladder.Choice(ladder.RUNG_TAR, "you chose to send the folder as an archive, one way")
        raise MigrateError("rung_unavailable", f"{override} cannot carry this project", 422)
    return chosen


def _task_files_probe(manifest: Mapping[str, Any], target_caps: Collection[str]) -> Tuple[Dict[str, Any], int, bool]:
    if task_manager_side.CAP_TASK_FILES_PLAN not in target_caps:
        return {}, 0, False
    try:
        parts, left_out = task_manager_side.task_file_parts(manifest["huddle"])
    except (KeyError, TypeError, AttributeError, RecursionError) as exc:
        logger.warning("pack_plan_task_files_probe_skipped", error=type(exc).__name__)
        return {}, 0, True
    return ({"task_file_parts": parts} if parts else {}), left_out, False


def _task_files_check(prep: Mapping[str, Any], label: str, unchecked: int = 0, failed: bool = False) -> List[Dict[str, Any]]:
    names, more = ops.listed_dropped_files({"task_files_not_copied": prep.get("task_files_not_copied")})
    broken = failed or bool(prep.get("task_files_check_failed"))
    if not names and not broken and not unchecked:
        return []
    parts: List[str] = []
    if names:
        parts.append(f"{len(names) + more} attached task file(s) will not be carried: {label} does not have them, and each one gets a note in its task thread")
    if broken or unchecked:
        parts.append("some task files could not be checked, so there may be more" if names else "some task files could not be checked, so some may not be carried")
    return [{**_check("task_files_not_carried", False, "; ".join(parts), blocking=False), "files": names, "files_more": more, "files_unchecked": unchecked,
             "files_check_failed": broken}]


def build_manifest(env: SourceEnv, project: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    with closing(env.open_db()) as conn:
        manifest = manifest_mod.collect(conn, project, env.state_dir)
    for s in manifest["sessions"]:
        key = env.account_of(s["session_uuid"])
        if key:
            s["account_key"] = key
    files = transcripts.source_files(project["root"])
    manifest["transcripts"] = [{k: f[k] for k in ("rel", "size", "sha256")} for f in files]
    return manifest, files


def _fingerprint(project: Mapping[str, Any], target: str, root: str, case: str, rung: str, meta: Mapping[str, Any], manifest: Mapping[str, Any],
                 live: Sequence[str] = (), units: Sequence[Any] = ()) -> str:
    material = {"uid": project["uid"], "root": project["root"], "target": target, "target_root": root, "case": case, "rung": rung,
                "head": meta.get("head"), "branch": meta.get("branch"), "stats": meta.get("stats"), "units": list(units),
                "manifest": hashlib.sha256(json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest() if not live else sorted(live)}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def plan_project(env: SourceEnv, project: Dict[str, Any], target_install_id: str, request: Request, *, root_hint: Optional[str] = None,
                       rung: Optional[str] = None, parent_id: Optional[str] = None, stop_running: bool = False,
                       target_caps: Collection[str] = ()) -> Plan:
    if project.get("pack_state") != home.HOME:
        raise MigrateError("project_moved_away" if project.get("pack_state") == home.MOVED_AWAY else "not_project_home",
                           "only the active home of a project can migrate it", 409)
    air_gap = bool(project.get("air_gap"))
    described = await asyncio.to_thread(code.describe, project["root"], air_gap=air_gap)
    chosen = choose(project, described, None if rung == ladder.RUNG_UNITS else rung)
    found: Optional[scan.CarrySet] = None
    if chosen.rung == ladder.RUNG_TAR and rung in (None, ladder.RUNG_UNITS) and scan.CARRY_TREE in target_caps:
        found = await asyncio.to_thread(scan.scan_project, project["root"], air_gap=air_gap)
        if found.nested:
            chosen = ladder.Choice(ladder.RUNG_UNITS, "the folder holds git repos, so each goes over the link with its history and uncommitted work, and the loose files with them")
        else:
            found = None
    meta: Dict[str, Any] = {k: described[k] for k in ("branch", "head", "remote")}
    if chosen.rung in (ladder.RUNG_TAR, ladder.RUNG_UNITS):
        meta["stats"] = await asyncio.to_thread(code.tree_stats, project["root"])
    manifest, files = await asyncio.to_thread(build_manifest, env, project)
    with closing(env.open_db()) as conn:
        agents, blockers = live_agents.read(conn, project["id"])
        company = _company(conn, project)
        label = env.label_of(target_install_id)
        card = None
        if chosen.rung == ladder.RUNG_TAR and not air_gap:
            res = github_account.resolve(air_gap=False, project_account=project.get("github_account"), company_account=_owner_pointer(company, "github_login"), origin_url=None)
            card = publish.card(display_name=project["display_name"], air_gap=False, has_remote=False, owner_pointer=_owner_pointer(company, "github"), account=res)
    shells, screen_blockers = await live_agents.classify(agents, env.find_live, stop_running)
    blockers += screen_blockers
    size = sum(f["size"] for f in files) + (meta.get("stats") or {}).get("bytes", 0)
    probe, unchecked, probe_failed = _task_files_probe(manifest, target_caps)
    prep = await call(request, PREPARE, {
        "op_id": "dry", "dry_run": True, "project_uid": project["uid"], "name": project["display_name"], "root_hint": root_hint,
        "company_uid": manifest["company"]["uid"] if manifest["company"] else None, "bytes_needed": size, "parent_id": parent_id, **probe}, "prepare")
    use = chosen
    if chosen.rung == ladder.RUNG_GIT and prep["case"] != "new":
        use = ladder.Choice(ladder.RUNG_CARRIED, "the other computer already holds this project, so carnivore carries the commits over the link")
    checks = [
        _check("agents_ready", not blockers, "the move can put every live agent to sleep itself" if not blockers else "; ".join(blockers[:5])),
        _check("target_accepts", True, f"{label} takes the project at {prep['root']}"),
        _check("detached_head", not (use.rung == ladder.RUNG_CARRIED and described["branch"] is None), "the repo is on a branch" if described["branch"] else "check out a branch first: a detached HEAD cannot be carried"),
        _check("uncommitted_changes", not (use.rung != ladder.RUNG_TAR and described["dirty"]),
               f"{described['dirty']} uncommitted file(s) stay in the old folder, which is kept" if described["dirty"] else "the working tree is clean", blocking=False),
    ]
    checks += _task_files_check(prep, label, unchecked, probe_failed)
    if agents:
        checks.append(_check("live_agents", True, live_agents.sentence(len(agents), shells, label), blocking=False))
    if found is not None and use.rung == ladder.RUNG_UNITS:
        refusal = scan.blockers(found, label, target_caps)
        view = found.view(carries_wip=True)
        checks.append(_check("carry", refusal is None, refusal[1] if refusal else f"{len(found.repos)} repo(s) and {len(found.files)} loose file(s) go over the link"))
        dirty = sum(r.dirty for r in found.repos)
        if dirty:
            checks.append(_check("carried_work", True, f"{dirty} uncommitted file(s) in the repos are carried with them", blocking=False))
        if view["left_behind"]:
            checks.append(_check("left_behind", True, "stays in the old folder: " + ", ".join(f"{x['what']} ({x['why']})" for x in view["left_behind"][:5]), blocking=False))
    if use.rung == ladder.RUNG_TAR:
        checks.append(_check("one_way", False, "the copies will not stay in sync: this is a one-way move and the old folder is kept, inactive", blocking=False))
    plan = Plan(project=project, target_install_id=target_install_id, target_label=label, target_root=prep["root"], case=prep["case"], rung=use.rung,
                reason=use.reason, one_way=use.rung == ladder.RUNG_TAR, code_meta=meta, checks=checks, summary={**manifest_mod.summary(manifest), "transcript_files": len(files),
                "transcript_bytes": sum(f["size"] for f in files), "tar_files": (meta.get("stats") or {}).get("files"),
                "live_agents": len(agents), "background_shells": shells}, manifest=manifest, files=files, publish_card=card, target_caps=tuple(target_caps), carry=found if use.rung == ladder.RUNG_UNITS else None)
    plan.fingerprint = _fingerprint(project, target_install_id, prep["root"], prep["case"], use.rung, meta, manifest, [a.session_uuid for a in agents],
                                  [(r.rel, r.head, r.dirty) for r in plan.carry.repos] + [len(plan.carry.files)] if plan.carry else ())
    return plan
