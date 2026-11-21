
from __future__ import annotations

import asyncio
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.pack.jobs import gitio, policy
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

MAX_TIPS = 2000
IGNORED_SHOWN = 20
ASK_TIMEOUT_S = 40.0
ASK_REAL_TIMEOUT_S = 330.0
PEER_REAL_TIMEOUT_S = 300.0
_HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MAX_ROOT = 1024
_MAX_NAME = 256
_MAX_COUNT = 10_000_000
_MAX_ANSWER_BYTES = 200_000
FAR_CODES = frozenset({"not_a_copy", "no_record", "too_many_refs", "job_running", "session_live", "git_failed", "dirty", "stash",
                      "unseen_commits", "worktrees", "no_trash", "other_volume"})
HOME_CODES = frozenset({"needs_update", "unreachable", "timeout", "refused", "bad_answer", "not_chosen", "unknown"})
DELETED_CODES = frozenset({"", "row_left"})

Ask = Callable[[str, Dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class FarAnswer:

    verdict: str
    code: str
    root: str = ""
    ignored: Tuple[str, ...] = ()
    ignored_more: int = 0


@dataclass
class WipeAnswer:

    unregistered: List[str] = field(default_factory=list)
    left: List[Dict[str, Any]] = field(default_factory=list)
    failed: List[Dict[str, Any]] = field(default_factory=list)
    deleted: List[Dict[str, Any]] = field(default_factory=list)
    kept: List[Dict[str, Any]] = field(default_factory=list)

    def wire(self) -> Dict[str, Any]:
        return {"unregistered": self.unregistered, "left": self.left, "failed": self.failed, "deleted": self.deleted, "kept": self.kept}


def _clean(text: Any, limit: int) -> Optional[str]:
    if not isinstance(text, str):
        return None
    return _CONTROL.sub("", text)[:limit]


def parse_answer(raw: Any, *, dry_run: bool) -> FarAnswer:
    bad = FarAnswer("kept", "bad_answer")
    if not isinstance(raw, dict) or len(repr(raw)) > _MAX_ANSWER_BYTES:
        return bad
    verdict, code = raw.get("verdict"), raw.get("code", "")
    root = _clean(raw.get("root", ""), _MAX_ROOT)
    names, more = raw.get("ignored", []), raw.get("ignored_more", 0)
    if root is None or not isinstance(code, str) or not isinstance(names, list) or isinstance(more, bool) or not isinstance(more, int):
        return bad
    if not 0 <= more <= _MAX_COUNT or any(_clean(n, _MAX_NAME) is None for n in names):
        return bad
    shown = tuple(_clean(n, _MAX_NAME) or "" for n in names[:IGNORED_SHOWN])
    more += max(0, len(names) - IGNORED_SHOWN)
    if verdict == ("deletable" if dry_run else "deleted") and code in (("",) if dry_run else DELETED_CODES):
        return FarAnswer(str(verdict), code, root, shown, more)
    if verdict == "kept" and code in FAR_CODES:
        return FarAnswer("kept", code, root, shown, more)
    return bad


def home_tips(root: str) -> Tuple[List[str], str]:
    try:
        cp = gitio.run(["-C", root, "--no-optional-locks", "for-each-ref", "--format=%(objectname) %(objecttype) %(*objecttype) %(*objectname) %(refname)",
                        "refs/heads", "refs/tags"], timeout=120.0)
    except JobError as exc:
        log.warning("pack_wipe_tips_git", code=exc.code)
        return [], "git_failed"
    tips = set()
    for line in gitio.out(cp).splitlines():
        parts = line.split(" ")
        name = parts[-1]
        if len(parts) < 5 or not (name.startswith("refs/heads/") or name.startswith("refs/tags/")) or not _HEX.match(parts[0]):
            continue
        if parts[1] == "tag":
            if parts[2] == "commit" and _HEX.match(parts[3]):
                tips.add(parts[3])
        elif parts[1] == "commit":
            tips.add(parts[0])
    if len(tips) > MAX_TIPS:
        return [], "too_many_refs"
    return sorted(tips), ""


def _capable(install_id: str) -> bool:
    from src.api.federation_pack_copies_routes import CAP_FORGET_COPY
    from src.core.federation import peer_links
    from src.core.pack.machines import capabilities

    links = peer_links.LINKS
    return links is not None and capabilities.has(links.capabilities(install_id), CAP_FORGET_COPY)


async def _ask(install_id: str, body: Dict[str, Any]) -> Any:
    from src.api import project_replica_routes as routes

    peer = await asyncio.to_thread(routes.find_peer, install_id)
    limit = routes.PEER_TIMEOUT_SECONDS if body.get("dry_run") else PEER_REAL_TIMEOUT_S
    return await routes.call_peer(peer, "POST", "/federation/pack/jobs/forget-copy", body, timeout=limit)


async def ask_one(install_id: str, project_uid: str, tips: List[str], *, dry_run: bool, ask: Optional[Ask] = None) -> FarAnswer:
    send = ask or _ask
    try:
        raw = await asyncio.wait_for(send(install_id, {"project_uid": project_uid, "tips": tips, "dry_run": dry_run}),
                                     ASK_TIMEOUT_S if dry_run else ASK_REAL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return FarAnswer("kept", "timeout")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return FarAnswer("kept", "unreachable" if detail.get("code") == "machine_unreachable" else "refused")
    except (ValueError, OSError) as exc:
        log.warning("pack_wipe_ask_failed", error=type(exc).__name__)
        return FarAnswer("kept", "unreachable")
    return parse_answer(raw, dry_run=dry_run)


async def check_all(project: Dict[str, Any], copies: List[Dict[str, Any]], *, tips: List[str], tips_code: str,
                    ask: Optional[Ask] = None, capable: Optional[Callable[[str], bool]] = None) -> List[Dict[str, Any]]:
    can = capable or _capable
    rows: List[Dict[str, Any]] = []
    for copy in copies:
        install_id = copy["install_id"]
        if tips_code:
            far = FarAnswer("kept", tips_code)
        elif not can(install_id):
            far = FarAnswer("kept", "needs_update")
        else:
            far = await ask_one(install_id, project["uid"], tips, dry_run=True, ask=ask)
        rows.append({"install_id": install_id, "label": copy["label"], "root": far.root or copy.get("root") or "", "verdict": far.verdict,
                     "code": far.code, "ignored": list(far.ignored), "ignored_more": far.ignored_more})
    return rows


async def _detach(name: str, uid: str, copy: Dict[str, Any], store: JobStore, out: WipeAnswer, *, remember: bool = True) -> None:
    from src.api import project_replica_routes

    install_id, label = copy["install_id"], copy["label"]
    try:
        await project_replica_routes.remove_project_replica(name, install_id)
    except HTTPException as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
        if exc.status_code != 404 or code != "unknown_replica":
            out.failed.append({"computer": label, "code": code or f"http_{exc.status_code}"})
            return
    policy.forget_auto_replica(store, uid, install_id)
    out.unregistered.append(label)
    if copy.get("root"):
        out.left.append({"computer": label, "root": copy["root"]})
        if remember:
            policy.record_detached_root(store, uid, install_id, copy["root"])


def _forget_home_row(uid: str, install_id: str) -> None:
    from src.api import project_replica_routes, projects_service
    from src.config import settings
    from src.core.pack.identity import home, replicas

    with closing(projects_service.open_db_or_503(settings)) as conn:
        replicas.forget_replica(conn, uid, install_id)
        home.notify_changed()
    project_replica_routes._sync_proxy_scope(install_id)


async def run(project: Dict[str, Any], copies: List[Dict[str, Any]], *, delete: bool, keep: Optional[str], tips: List[str],
              store: JobStore, only: Optional[List[str]] = None, tips_code: str = "", ask: Optional[Ask] = None, capable: Optional[Callable[[str], bool]] = None,
              detach_kept: bool = True) -> WipeAnswer:
    name, uid, out = project["name"], project["uid"], WipeAnswer()
    can = capable or _capable
    for copy in copies:
        install_id, label = copy["install_id"], copy["label"]
        if keep is not None and install_id == keep:
            continue
        if delete:
            if only is not None and install_id not in only:
                far = FarAnswer("kept", "not_chosen")
            elif tips_code:
                far = FarAnswer("kept", tips_code)
            elif not can(install_id):
                far = FarAnswer("kept", "needs_update")
            else:
                far = await ask_one(install_id, uid, tips, dry_run=False, ask=ask)
                if far.verdict == "kept" and far.code in ("timeout", "unreachable"):
                    probe = await ask_one(install_id, uid, tips, dry_run=True, ask=ask)
                    if probe.verdict == "kept" and probe.code == "no_record":
                        far = FarAnswer("deleted", "", probe.root)
                    else:
                        out.kept.append({"label": label, "code": "unknown", "root": copy.get("root") or ""})
                        continue
            if far.verdict == "deleted":
                policy.forget_auto_replica(store, uid, install_id)
                code = far.code
                try:
                    await asyncio.to_thread(_forget_home_row, uid, install_id)
                except (sqlite3.Error, HTTPException) as exc:
                    log.error("pack_wipe_home_row_left", error=type(exc).__name__)
                    code = "row_left"
                out.deleted.append({"label": label, "root": far.root or copy.get("root") or "", "code": code})
                continue
            out.kept.append({"label": label, "code": far.code, "root": far.root or copy.get("root") or ""})
            if not detach_kept:
                if far.code == "no_record":
                    policy.forget_auto_replica(store, uid, install_id)
                continue
        await _detach(name, uid, copy, store, out, remember=not (delete and far.code == "no_record"))
    return out


async def _ssh_host(host_key: str) -> Any:
    from src.api.hosts_routes import _call
    from src.core.hosts import store as hosts_store

    try:
        host, _counts = await _call(hosts_store.get_host, host_key)
    except HTTPException:
        return None
    return host


def _ssh_holders(store: JobStore, uid: str) -> List[str]:
    return [str(r["host_key"]) for r in store.ssh_targets_all() if store.ssh_seed_get(uid, str(r["host_key"])) is not None]


async def ssh_holding(store: JobStore, uid: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for key in await asyncio.to_thread(_ssh_holders, store, uid):
        host = await _ssh_host(key)
        out.append({"key": key, "label": str(getattr(host, "label", "") or key)})
    return out


async def forget_ssh(store: JobStore, uid: str) -> List[Dict[str, str]]:
    from src.core.pack.jobs.ssh import owner

    rows: List[Dict[str, str]] = []
    for item in await ssh_holding(store, uid):
        host = await _ssh_host(item["key"])
        if host is None:
            rows.append({**item, "code": "no_host"})
            continue
        try:
            got = await owner.forget_folders(store, host, only_uid=uid)
        except JobError as exc:
            rows.append({**item, "code": exc.code})
            continue
        except (OSError, asyncio.TimeoutError) as exc:
            log.warning("pack_wipe_ssh_failed", error=type(exc).__name__)
            rows.append({**item, "code": "unreachable"})
            continue
        code = got["refused"][0]["code"] if got["refused"] else ("kept_slot" if got["kept"] else "forgotten")
        rows.append({**item, "code": code})
    return rows
