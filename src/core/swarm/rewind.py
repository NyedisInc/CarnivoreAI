
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.swarm import body, commit, memory, push, sleep_commit, store, thread_port
from src.core.swarm.gitrun import run_git

logger = structlog.get_logger()

CHECKPOINT_LIMIT = 50
CONVERSATION_LIMIT = 50
GIT_TIMEOUT_S = 60
_SHA = re.compile(r"[0-9a-f]{7,40}")
_FIELD = "\x1f"
NOT_IN_GIT = "its memory is local to this computer and is not in git, so there is nothing to rewind"


class RewindRefused(ValueError):
    pass


def _folder(agent: Dict[str, Any]) -> Optional[str]:
    if agent["rank"] == "task" or agent["memory_scope"] != memory.SCOPE_PROJECT or not agent.get("repo_dir"):
        return None
    repo = Path(agent["repo_dir"])
    return str(memory.memory_dir(repo, agent["slug"], memory.SCOPE_PROJECT).relative_to(repo)) if repo.is_dir() else None


def _kind(slug: str, subject: str) -> str:
    for prefix in ("swarm", "pack"):
        if subject.startswith(f"{prefix}: {slug} promoted to"):
            return "promotion"
        if subject.startswith(f"{prefix}: {slug} flipped back"):
            return "flip_back"
        if subject.startswith(f"{prefix}: {slug} memory rewound"):
            return "rewind"
    return "memory"


def _log(repo: Path, folder: str, slug: str) -> List[Dict[str, str]]:
    out = run_git(repo, "log", f"-n{CHECKPOINT_LIMIT}", f"--format=%H{_FIELD}%aI{_FIELD}%s", "--", folder, timeout=GIT_TIMEOUT_S, optional_locks=False)
    if out.returncode != 0:
        raise RewindRefused("git could not read this repo's history")
    rows = []
    for line in out.stdout.splitlines():
        sha, at, subject = (line.split(_FIELD) + ["", ""])[:3]
        if sha:
            rows.append({"sha": sha, "at": at, "subject": subject, "kind": _kind(slug, subject)})
    return rows


async def checkpoints(agent: Dict[str, Any]) -> Dict[str, Any]:
    folder = _folder(agent)
    if folder is None:
        return {"commits": [], "reason": NOT_IN_GIT}
    try:
        commits = await asyncio.to_thread(_log, Path(agent["repo_dir"]), folder, agent["slug"])
    except (OSError, RewindRefused) as exc:
        return {"commits": [], "reason": str(exc) if isinstance(exc, RewindRefused) else "git is not available"}
    return {"commits": commits, "reason": None if commits else "this folder has no commits yet"}


def transcript_present(conn: sqlite3.Connection, agent: Dict[str, Any], conversation_uuid: str) -> bool:
    from src.core.session_imported_restart import DIRECTORY_MEASURED, resume_directory
    from src.core.transcript_manifest.store import path_for_conversation

    path = path_for_conversation(conn, conversation_uuid, agent["harness"])
    if path and os.path.isfile(path):
        return True
    return resume_directory(agent.get("repo_dir"), conversation_uuid, family=agent["harness"]).outcome == DIRECTORY_MEASURED


def conversations_blocking(conn: sqlite3.Connection, agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, conversation_uuid, started_at, reason, authority FROM swarm_wakes WHERE agent_id = ? "
                        "AND conversation_uuid IS NOT NULL AND conversation_uuid != '' ORDER BY id DESC LIMIT ?",
                        (agent["id"], CONVERSATION_LIMIT)).fetchall()
    return [{"wake_id": r["id"], "conversation_uuid": r["conversation_uuid"], "started_at": r["started_at"], "reason": r["reason"],
             "authority": r["authority"], "transcript_present": transcript_present(conn, agent, r["conversation_uuid"])} for r in rows]


async def conversations(agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    return await body.run_db(lambda c: conversations_blocking(c, agent))


def require_resumable(conn: sqlite3.Connection, agent: Dict[str, Any], conversation_uuid: str) -> None:
    mine = conn.execute("SELECT 1 FROM swarm_wakes WHERE agent_id = ? AND conversation_uuid = ? LIMIT 1", (agent["id"], conversation_uuid)).fetchone()
    if mine is None:
        raise RewindRefused("that conversation is not one of this agent's own")
    if not transcript_present(conn, agent, conversation_uuid):
        raise RewindRefused("that conversation's transcript is not on disk, so it cannot be resumed")


def _precheck(repo: Path, folder: str, sha: str, slug: str) -> str:
    blocked = commit._blocked_state(repo)
    if blocked:
        raise RewindRefused(f"the repo is {blocked.replace('_', ' ')}; rewind once it is clean")
    if not _SHA.fullmatch(sha):
        raise RewindRefused("that is not a commit sha")
    hits = [c["sha"] for c in _log(repo, folder, slug) if c["sha"].startswith(sha)]
    if len(hits) != 1:
        raise RewindRefused("that commit is not one of this agent's memory checkpoints")
    full = hits[0]
    if run_git(repo, "cat-file", "-e", f"{full}:{folder}", timeout=GIT_TIMEOUT_S, optional_locks=False).returncode != 0:
        raise RewindRefused("the memory folder did not exist at that checkpoint (it is the flip-back commit)")
    dirty = run_git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--", folder, timeout=GIT_TIMEOUT_S, optional_locks=False)
    if dirty.returncode != 0 or dirty.stdout.strip("\0"):
        raise RewindRefused("the memory folder has uncommitted changes that a rewind would overwrite; commit or discard them first")
    return full


def _restore(repo: Path, folder: str, source: str) -> None:
    done = run_git(repo, "restore", f"--source={source}", "--worktree", "--no-overlay", "--", folder, timeout=GIT_TIMEOUT_S)
    if done.returncode != 0:
        raise RewindRefused("git could not restore the memory folder")


def _put_back(repo: Path, folder: str) -> None:
    try:
        run_git(repo, "restore", "--source=HEAD", "--worktree", "--no-overlay", "--", folder, timeout=GIT_TIMEOUT_S)
        added = run_git(repo, "ls-files", "-o", "--exclude-standard", "-z", "--", folder, timeout=GIT_TIMEOUT_S, optional_locks=False)
        root = os.path.realpath(repo / folder)
        for rel in filter(None, added.stdout.split("\0")):
            path = repo / rel
            if (os.path.realpath(path.parent) + os.sep).startswith(root + os.sep) and not path.is_dir():
                path.unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("swarm_rewind_put_back_failed", error_type=type(exc).__name__)


async def _rewind_locked(agent_id: int, sha: str) -> tuple:
    got = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if got is None or got["torn_down_at"] is not None:
        raise RewindRefused("that agent is torn down")
    if got["state"] != "asleep":
        raise RewindRefused(f"{got['display_name']} is {got['state']}; put it to sleep first so its memory is committed, then rewind")
    folder = _folder(got)
    if folder is None:
        raise RewindRefused(NOT_IN_GIT)
    repo = Path(got["repo_dir"])
    lock = sleep_commit._repo_locks.setdefault(str(repo), asyncio.Lock())
    try:
        async with lock:
            full = await asyncio.to_thread(_precheck, repo, folder, sha, got["slug"])
            await asyncio.to_thread(_restore, repo, folder, full)
    except OSError as exc:
        raise RewindRefused(f"git is not available: {exc.__class__.__name__}") from None
    short = full[:8]
    result = await sleep_commit.run(got, f"swarm: {got['slug']} memory rewound to {short}") or {}
    status = result.get("status")
    if status not in (commit.COMMITTED, commit.NOTHING):
        async with lock:
            await asyncio.to_thread(_put_back, repo, folder)
        why = {commit.PENDING_APPROVAL: "this repo's origin is public or unknown: approve memory commits on the card first",
               commit.REFUSED_SECRET: f"a restored file looks like a credential ({result.get('detail')}), so nothing was changed"}.get(
                   status, f"the commit did not land ({result.get('reason') or 'git failed'}), so nothing was changed")
        raise RewindRefused(why)
    if status == commit.COMMITTED:
        await body.run_db(lambda c: (store.stamp_last_conversation(c, agent_id), store.clear_conversation(c, agent_id)))
    return got, full, short, result, status


async def rewind(app_state: Any, agent_id: int, sha: str) -> Dict[str, Any]:
    async with body.agent_lock(agent_id):
        got, full, short, result, status = await _rewind_locked(agent_id, sha)
    if status == commit.COMMITTED:
        await _card(got, short, result["sha"])
        await asyncio.to_thread(push.notify_agent, agent_id)
    logger.info("swarm_rewound", agent_id=agent_id, to=short, status=status)
    return {"state": "asleep", "commit": {"status": status, "sha": result.get("sha") or None, "skipped_reason": None}}


async def _card(agent: Dict[str, Any], short: str, new_sha: str) -> None:
    port = thread_port.get()
    if port is None:
        return
    text = (f"{agent['display_name']}'s memory was rewound to {short} in a new commit ({new_sha[:8]}). Its next wake starts a fresh "
            f"conversation. To undo, rewind to the checkpoint just before {new_sha[:8]}.")
    try:
        await port.post_card(agent["thread_key"], "info", "memory rewound", text, f"rewind:{agent['id']}:{new_sha[:8]}")
        await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_rewind_card_failed", agent_id=agent["id"], error_type=type(exc).__name__)
