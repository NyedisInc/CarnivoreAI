from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.pack.transport import github_account, ladder

logger = structlog.get_logger()

TTL_OPEN, TTL_NONE, TTL_DONE = 60.0, 120.0, 600.0
CALL_TIMEOUT = 20.0
BACKOFF_START, BACKOFF_MAX = 60.0, 600.0

QUERY = """query($owner:String!,$name:String!){repository(owner:$owner,name:$name){pullRequests(first:50,
states:[OPEN,MERGED,CLOSED],orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number url state isDraft headRefName
headRepositoryOwner{login} mergeable reviewDecision reviewThreads(first:50){nodes{isResolved}}
commits(last:1){nodes{commit{statusCheckRollup{state}}}}}}}}"""

_REPO_RE = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.IGNORECASE)
_CI = {"SUCCESS": "green", "FAILURE": "red", "ERROR": "red", "PENDING": "pending", "EXPECTED": "pending"}


def parse(raw: str) -> List[Dict[str, Any]]:
    data = json.loads(raw)
    nodes = (((data.get("data") or {}).get("repository") or {}).get("pullRequests") or {}).get("nodes") or []
    out = []
    for n in nodes:
        state = str(n.get("state") or "").lower()
        if state == "open" and n.get("isDraft"):
            state = "draft"
        commits = ((n.get("commits") or {}).get("nodes") or [])
        rollup = ((commits[-1].get("commit") or {}).get("statusCheckRollup") or {}) if commits else {}
        review = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes", "REVIEW_REQUIRED": "review"}.get(
            n.get("reviewDecision") or "")
        threads = ((n.get("reviewThreads") or {}).get("nodes") or [])
        out.append({
            "number": int(n.get("number") or 0), "url": str(n.get("url") or ""), "state": state,
            "branch": str(n.get("headRefName") or ""),
            "head_owner": str(((n.get("headRepositoryOwner") or {}).get("login")) or "").lower(),
            "ci": _CI.get(str(rollup.get("state") or "")), "review": review,
            "conflict": n.get("mergeable") == "CONFLICTING",
            "unresolved": sum(1 for t in threads if not t.get("isResolved")),
        })
    return out


def match(prs: List[Dict[str, Any]], branch: str, owner: str) -> Optional[Dict[str, Any]]:
    mine = [p for p in prs if p["branch"] == branch and p["head_owner"] == owner.lower()]
    live = [p for p in mine if p["state"] in ("open", "draft")]
    return (live or mine or [None])[0]


def repo_of(url: Optional[str]) -> Optional[Tuple[str, str]]:
    m = _REPO_RE.search(url or "")
    return (m.group("owner"), m.group("name")) if m else None


@dataclass
class Target:

    branch: Optional[str]
    repo: Optional[Tuple[str, str]]
    account: Optional[str]
    hint: Optional[str] = None


def _git(folder: str, *args: str) -> Optional[str]:
    try:
        done = ladder.run(["git", "-C", folder, *args], air_gap=False, timeout=10.0)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = done.stdout.decode("utf-8", "replace").strip()
    return out if done.returncode == 0 and out else None


def _project_for(folder: str) -> Optional[Dict[str, Any]]:
    from src.config import settings
    from src.core.companies import accounts as company_accounts
    from src.core.db import connect, db_path_for

    import sqlite3

    real = os.path.realpath(folder)
    try:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            rows = conn.execute("SELECT root, air_gap, github_account, company_id FROM projects "
                                "WHERE archived_at IS NULL AND COALESCE(host_key, 'local') = 'local'").fetchall()
            best = None
            for root, air_gap, account, company_id in rows:
                r = os.path.realpath(str(root or ""))
                if r and (real == r or real.startswith(r.rstrip("/") + "/")) and (best is None or len(r) > len(best[0])):
                    best = (r, air_gap, account, company_id)
            if best is None:
                return None
            company = None
            if best[3] is not None:
                try:
                    company = company_accounts.get_accounts(conn, best[3]).get("github_login")
                except (sqlite3.Error, LookupError, ValueError) as exc:
                    logger.info("pr_status_company_unreadable", error=type(exc).__name__)
            return {"air_gap": bool(best[1]), "github_account": best[2], "company_account": company}
    except (sqlite3.Error, OSError) as exc:
        logger.info("pr_status_projects_unreadable", error=type(exc).__name__)
        return None


def resolve_target(folder: str) -> Target:
    project = _project_for(folder) or {}
    if project.get("air_gap"):
        return Target(None, None, None)
    branch = _git(folder, "symbolic-ref", "--quiet", "--short", "HEAD")
    origin = _git(folder, "remote", "get-url", "origin")
    repo = repo_of(origin)
    if not branch or repo is None:
        return Target(branch, None, None)
    res = github_account.resolve(air_gap=False, project_account=project.get("github_account"),
                                 company_account=project.get("company_account"), origin_url=origin)
    return Target(branch, repo, res.account, None if res.account else "connect_gh")


def fetch(account: str, repo: Tuple[str, str]) -> str:
    gh = github_account.gh_path()
    if gh is None:
        raise github_account.AccountError("gh_missing", "gh is not installed on this computer")
    env = github_account.token_env(account)
    try:
        done = ladder.run([gh, "api", "graphql", "-f", f"query={QUERY}", "-F", f"owner={repo[0]}", "-F", f"name={repo[1]}"],
                          air_gap=False, env=env, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise FetchFailed("gh timed out") from None
    if done.returncode != 0:
        err = done.stderr.decode("utf-8", "replace")
        if "rate limit" in err.lower():
            raise RateLimited("rate limited")
        raise FetchFailed(f"gh exited {done.returncode}")
    return done.stdout.decode("utf-8", "replace")


class RateLimited(RuntimeError):
    pass


class FetchFailed(RuntimeError):
    pass


@dataclass
class _Repo:
    prs: Optional[List[Dict[str, Any]]] = None
    fetched_at: float = 0.0
    ttl: float = 0.0
    stale: bool = False
    backoff: float = 0.0
    retry_at: float = 0.0


@dataclass
class PrWatch:

    resolve: Callable[[str], Target] = resolve_target
    call: Callable[[str, Tuple[str, str]], str] = fetch
    clock: Callable[[], float] = time.monotonic
    _wanted: Set[str] = field(default_factory=set)
    _targets: Dict[str, Tuple[float, Target]] = field(default_factory=dict)
    _repos: Dict[Tuple[str, str, str], _Repo] = field(default_factory=dict)
    _inflight: Set[Tuple[str, str, str]] = field(default_factory=set)
    _task: Optional[asyncio.Task] = None

    def badge(self, folder: Optional[str]) -> Optional[Dict[str, Any]]:
        if not folder:
            return None
        self._wanted.add(folder)
        entry = self._targets.get(folder)
        if entry is None:
            return None
        target = entry[1]
        if target.hint:
            return {"hint": target.hint}
        if not (target.account and target.repo and target.branch):
            return None
        cached = self._repos.get((target.account, *target.repo))
        if cached is None or cached.prs is None:
            return None
        pr = match(cached.prs, target.branch, target.repo[0])
        return {**pr, "stale": cached.stale} if pr else None

    def tick(self, wake: Callable[[], None]) -> None:
        if not self._wanted or (self._task is not None and not self._task.done()):
            return
        wanted, self._wanted = set(self._wanted), set()
        self._task = asyncio.get_running_loop().create_task(self._refresh(wanted, wake))

    async def _refresh(self, folders: Set[str], wake: Callable[[], None]) -> None:
        now = self.clock()
        changed = False
        for folder in folders:
            seen = self._targets.get(folder)
            if seen is None or now - seen[0] > TTL_NONE:
                self._targets[folder] = (now, await asyncio.to_thread(self.resolve, folder))
                changed = True
        for gone in set(self._targets) - folders:
            self._targets.pop(gone, None)
        due = {(t.account, *t.repo) for _, t in self._targets.values() if t.account and t.repo}
        for key in due:
            if key in self._inflight:
                continue
            repo = self._repos.setdefault(key, _Repo())
            if now < repo.retry_at or (repo.prs is not None and now - repo.fetched_at < repo.ttl):
                continue
            self._inflight.add(key)
            try:
                changed |= await self._fetch_one(key, repo, now)
            finally:
                self._inflight.discard(key)
        if changed:
            wake()

    async def _fetch_one(self, key: Tuple[str, str, str], repo: _Repo, now: float) -> bool:
        before = (repo.prs, repo.stale)
        try:
            prs = parse(await asyncio.to_thread(self.call, key[0], (key[1], key[2])))
        except RateLimited:
            repo.backoff = min(BACKOFF_MAX, max(BACKOFF_START, repo.backoff * 2))
            repo.retry_at, repo.stale = now + repo.backoff, True
            logger.info("pr_status_rate_limited", repo=f"{key[1]}/{key[2]}", backoff=repo.backoff)
            return before != (repo.prs, repo.stale)
        except (FetchFailed, github_account.AccountError, ValueError) as exc:
            repo.stale, repo.retry_at = True, now + TTL_OPEN
            logger.info("pr_status_failed", repo=f"{key[1]}/{key[2]}", error=type(exc).__name__)
            return before != (repo.prs, repo.stale)
        branches = {t.branch for _, t in self._targets.values() if t.repo and (t.account, *t.repo) == key}
        hits = [m for m in (match(prs, b, key[1]) for b in branches if b) if m]
        repo.ttl = TTL_NONE if not hits else (TTL_OPEN if any(h["state"] in ("open", "draft") for h in hits) else TTL_DONE)
        repo.prs, repo.fetched_at, repo.stale, repo.backoff = prs, now, False, 0.0
        return before != (repo.prs, repo.stale)


PR_WATCH = PrWatch()
