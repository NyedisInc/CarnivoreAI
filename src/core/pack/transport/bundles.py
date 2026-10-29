
from __future__ import annotations

import os
import re
import sqlite3
from typing import List, Optional, Sequence

import structlog

from src.core.pack.transport import ladder
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

_INSTALL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")


class BundleError(Exception):
    """A bundle could not be made or applied; ``code`` is the stable reason. The message never carries file content."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _git(repo: str, *args: str, air_gap: bool, timeout: float = 300.0):
    return ladder.run(["git", "-C", repo, *args], air_gap=air_gap, timeout=timeout)


def ref_tips(repo: str, *, air_gap: bool) -> List[str]:
    done = _git(repo, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/tags", air_gap=air_gap)
    if done.returncode != 0:
        raise BundleError("not_a_repo", "the folder is not a git repository")
    return sorted({ln.strip() for ln in done.stdout.decode().splitlines() if _SHA_RE.match(ln.strip())})


def is_repo(path: str) -> bool:
    done = ladder.run(["git", "-C", path, "rev-parse", "--show-toplevel"], air_gap=False, timeout=30.0)
    return done.returncode == 0 and os.path.realpath(done.stdout.decode().strip()) == os.path.realpath(path)


def origin_url(repo: str) -> Optional[str]:
    done = ladder.run(["git", "-C", repo, "config", "--get", "remote.origin.url"], air_gap=False, timeout=30.0)
    value = done.stdout.decode().strip()
    return value if done.returncode == 0 and value else None


def current_branch(repo: str) -> Optional[str]:
    done = ladder.run(["git", "-C", repo, "symbolic-ref", "--short", "-q", "HEAD"], air_gap=False, timeout=30.0)
    value = done.stdout.decode().strip()
    return value if done.returncode == 0 and value else None


def carry_branch(repo: str) -> str:
    named = current_branch(repo)
    if named:
        return named
    at_head = ladder.run(["git", "-C", repo, "for-each-ref", "--points-at", "HEAD", "--format=%(refname:short)", "refs/heads"],
                         air_gap=False, timeout=30.0).stdout.decode().split()
    if at_head:
        return sorted(at_head, key=lambda b: (b not in ("main", "master"), b))[0]
    done = ladder.run(["git", "-C", repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"], air_gap=False, timeout=30.0)
    value = done.stdout.decode().strip()
    if done.returncode == 0 and value.startswith("origin/") and len(value) > len("origin/"):
        return value[len("origin/"):]
    raise BundleError("detached_head_no_branch", "the repo is on a detached HEAD that no branch points at and origin names no default branch: check a branch out first")


def make_bundle(repo: str, dest: str, *, known_tips: Sequence[str], air_gap: bool, full: bool = False) -> Optional[List[str]]:
    tips = ref_tips(repo, air_gap=air_gap)
    if not tips:
        return None
    if not full and known_tips and set(tips) <= set(known_tips):
        return None
    base = [] if full else [f"^{t}" for t in known_tips if _SHA_RE.match(t)]
    done = None
    for extra in ([base, []] if base else [[]]):
        done = _git(repo, "bundle", "create", dest, "--branches", "--tags", *extra, air_gap=air_gap)
        if done.returncode == 0:
            return tips
        if b"empty bundle" in done.stderr.lower():
            return None
        if os.path.exists(dest):
            os.unlink(dest)
    logger.warning("pack_bundle_create_failed", status=done.returncode if done else None)
    raise BundleError("bundle_failed", "git could not make the bundle")


def apply_bundle(repo: str, bundle: str, sender_install_id: str, *, air_gap: bool) -> int:
    if not _INSTALL_RE.match(sender_install_id or "") or ".." in sender_install_id:
        raise BundleError("bad_sender", "the sender's install id is not usable in a ref name")
    if _git(repo, "rev-parse", "--git-dir", air_gap=air_gap).returncode != 0:
        if _git(repo, "init", "-q", air_gap=air_gap).returncode != 0:
            raise BundleError("bundle_apply_failed", "git could not initialise the replica folder")
    verified = _git(repo, "bundle", "verify", bundle, air_gap=air_gap)
    if verified.returncode != 0:
        raise BundleError("bundle_unverified", "the bundle does not verify against this checkout")
    ns = f"refs/carnivore/{sender_install_id}"
    done = _git(repo, "fetch", "--no-tags", "--force", "--prune", bundle,
                f"+refs/heads/*:{ns}/heads/*", f"+refs/tags/*:{ns}/tags/*", air_gap=air_gap, timeout=600.0)
    if done.returncode != 0:
        logger.warning("pack_bundle_apply_failed", status=done.returncode, stderr_bytes=len(done.stderr))
        raise BundleError("bundle_apply_failed", "git could not fetch the bundle")
    listed = _git(repo, "for-each-ref", "--format=%(refname)", ns, air_gap=air_gap)
    return len([ln for ln in listed.stdout.decode().splitlines() if ln.strip()])


def read_tips(conn: sqlite3.Connection, project_uid: str, install_id: str, direction: str = "out") -> List[str]:
    row = conn.execute("SELECT last_tip_sha FROM pack_bundle_tips WHERE project_uid = ? AND install_id = ? AND direction = ?",
                       (project_uid, install_id, direction)).fetchone()
    return [t for t in (row[0] if row else "").split() if _SHA_RE.match(t)]


def record_tips(conn: sqlite3.Connection, project_uid: str, install_id: str, tips: Sequence[str], direction: str = "out") -> None:
    conn.execute("INSERT INTO pack_bundle_tips (project_uid, install_id, direction, last_tip_sha, at) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(project_uid, install_id, direction) DO UPDATE SET last_tip_sha = excluded.last_tip_sha, at = excluded.at",
                 (project_uid, install_id, direction, " ".join(tips), utc_now()))
