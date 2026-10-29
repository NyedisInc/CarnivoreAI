
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import structlog

from src.core.swarm import store
from src.core.swarm.gitrun import run_git

logger = structlog.get_logger(__name__)

GIT_TIMEOUT_S = 15
API_TIMEOUT_S = 5.0
UNREADABLE = "unreadable"
_RANK = {"private": 0, "unknown": 1, "public": 2}
_GITHUB_RE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|ssh://(?:[^@/]+@)?github\.com(?::\d+)?/|git@github\.com:)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

Fetch = Callable[[str, str], str]


def read_remotes(repo: Path) -> Optional[List[Tuple[str, str, str]]]:
    try:
        listed = run_git(repo, "remote", timeout=GIT_TIMEOUT_S, optional_locks=False)
        if listed.returncode != 0:
            return None
        triples: List[Tuple[str, str, str]] = []
        for name in listed.stdout.split():
            for kind, flags in (("fetch", ()), ("push", ("--push",))):
                out = run_git(repo, "remote", "get-url", *flags, "--all", name, timeout=GIT_TIMEOUT_S,
                              optional_locks=False)
                if out.returncode != 0:
                    return None
                triples.extend((name, kind, url) for url in out.stdout.split("\n") if url.strip())
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("swarm_remotes_read_failed", error=type(exc).__name__)
        return None
    return sorted(triples)


def fingerprint(remotes: Optional[List[Tuple[str, str, str]]]) -> str:
    if remotes is None:
        return UNREADABLE
    return hashlib.sha256("\n".join("\t".join(t) for t in remotes).encode("utf-8", "surrogateescape")).hexdigest()


def parse_github(url: str) -> Optional[Tuple[str, str]]:
    m = _GITHUB_RE.match(url.strip())
    return (m.group("owner"), m.group("repo")) if m else None


def redact_url(url: str) -> str:
    return re.sub(r"^([a-z][a-z0-9+.-]*://)[^@/]+@", r"\1", url.strip())


def fetch_visibility(owner: str, repo: str) -> str:
    try:
        resp = httpx.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=API_TIMEOUT_S,
                         headers={"Accept": "application/vnd.github+json"}, follow_redirects=False)
    except httpx.HTTPError as exc:
        logger.info("swarm_visibility_fetch_failed", error=type(exc).__name__)
        return "unknown"
    if resp.status_code == 404:
        return "private"
    if resp.status_code != 200:
        return "unknown"
    try:
        private = resp.json().get("private")
    except (ValueError, AttributeError):
        return "unknown"
    if private is False:
        return "public"
    return "private" if private is True else "unknown"


def classify(remotes: Optional[List[Tuple[str, str, str]]], fetch: Fetch) -> Tuple[str, Optional[str]]:
    if remotes is None:
        return "unknown", None
    if not remotes:
        return "local", None
    seen: Dict[Tuple[str, str], str] = {}
    worst: Tuple[str, str] = ("private", remotes[0][2])
    for _name, _kind, url in remotes:
        gh = parse_github(url)
        if gh is None:
            verdict = "unknown"
        else:
            if gh not in seen:
                seen[gh] = fetch(*gh)
            verdict = seen[gh]
        if verdict not in _RANK:
            verdict = "unknown"
        if _RANK[verdict] > _RANK[worst[0]]:
            worst = (verdict, url)
    return worst[0], redact_url(worst[1])


def check(conn: sqlite3.Connection, repo_dir: str, *, fetch: Fetch = fetch_visibility) -> Dict[str, Any]:
    remotes = read_remotes(Path(repo_dir))
    fp = fingerprint(remotes)
    row = store.get_visibility(conn, repo_dir)
    if row and row.get("remote_fingerprint") == fp and (row["approved_at"] or row["visibility"] in ("private", "local")):
        return row
    if remotes is None:
        logger.info("swarm_visibility_unreadable", repo=repo_dir)
        return {"repo_dir": repo_dir, "visibility": "unknown", "remote_url": None, "approved_at": None,
                "remote_fingerprint": fp}
    verdict, url = classify(remotes, fetch)
    store.upsert_visibility(conn, repo_dir, visibility=verdict, remote_url=url, remote_fingerprint=fp)
    logger.info("swarm_visibility_checked", repo=repo_dir, visibility=verdict)
    return store.get_visibility(conn, repo_dir) or {}


def approve(conn: sqlite3.Connection, repo_dir: str, remote_fingerprint: str) -> bool:
    if fingerprint(read_remotes(Path(repo_dir))) != remote_fingerprint:
        return False
    return store.approve_visibility(conn, repo_dir, remote_fingerprint)


def needs_approval(row: Dict[str, Any]) -> bool:
    return row.get("visibility") in ("public", "unknown") and not row.get("approved_at")
