
from __future__ import annotations

import errno
import fcntl
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import List

import structlog

from src.core.message_model_secrets import EXTRA_VENDOR_DETECTORS, VENDOR_DETECTORS, scan_text
from src.core.swarm.gitrun import run_git
from src.core.session_git.secret_names import is_secret_path
from src.models.session_git import GitFile, SessionGitDiff

log = structlog.get_logger()

MAX_BYTES = 256 * 1024
TIMEOUT_S = 8.0
_BINARY_SNIFF = 8000
_BINARY_LINE = re.compile(r"^Binary files .* differ$", re.MULTILINE)


class EscapesRepository(Exception):
    pass


def _cap(text: str) -> "tuple[str, bool]":
    raw = text.encode("utf-8", "surrogateescape")
    return raw[:MAX_BYTES].decode("utf-8", "replace"), len(raw) > MAX_BYTES


def _inside(root: Path, rel: str) -> None:
    target = root / rel
    if not os.path.lexists(target):
        return
    try:
        real_root = root.resolve()
        parent = (target.parent).resolve()
        if parent != real_root and real_root not in parent.parents:
            raise EscapesRepository(rel)
        if target.is_symlink():
            real = target.resolve()
            if real != real_root and real_root not in real.parents:
                raise EscapesRepository(rel)
    except (RuntimeError, OSError):
        raise EscapesRepository(rel)


def _fd_real_path(fd: int) -> str:
    if hasattr(fcntl, "F_GETPATH"):
        return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0])
    return os.readlink(f"/proc/self/fd/{fd}")


def _read_contained(root: Path, rel: str) -> bytes:
    try:
        fd = os.open(root / rel, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise EscapesRepository(rel)
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
            raise EscapesRepository(rel)
        real_root = os.path.realpath(root)
        real = os.path.realpath(_fd_real_path(fd))
        if real != real_root and not real.startswith(real_root.rstrip(os.sep) + os.sep):
            raise EscapesRepository(rel)
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read(MAX_BYTES + 1)
    finally:
        os.close(fd)


def _added_diff(rel: str, content: bytes, truncated: bool) -> str:
    text = content.decode("utf-8", "replace")
    lines = text.splitlines()
    out: List[str] = [f"diff --git a/{rel} b/{rel}", "new file mode 100644", "--- /dev/null", f"+++ b/{rel}"]
    if lines:
        out.append(f"@@ -0,0 +1,{len(lines)} @@")
        out.extend("+" + line for line in lines)
        if not truncated and not text.endswith("\n"):
            out.append("\\ No newline at end of file")
    return "\n".join(out) + "\n"


def _untracked(root: Path, rel: str) -> SessionGitDiff:
    target = root / rel
    if target.is_symlink():
        text, _ = _cap(f"diff --git a/{rel} b/{rel}\nnew file mode 120000\n--- /dev/null\n+++ b/{rel}\n"
                       f"@@ -0,0 +1 @@\n+{os.readlink(target)}\n\\ No newline at end of file\n")
        return SessionGitDiff(state="ok", path=rel, text=text, untracked=True)
    content = _read_contained(root, rel)
    if b"\0" in content[:_BINARY_SNIFF]:
        return SessionGitDiff(state="ok", path=rel, untracked=True, binary=True)
    truncated = len(content) > MAX_BYTES
    text, cut = _cap(_added_diff(rel, content[:MAX_BYTES], truncated))
    return SessionGitDiff(state="ok", path=rel, text=text, truncated=truncated or cut, untracked=True)


def _screened(result: SessionGitDiff, entry: GitFile) -> SessionGitDiff:
    if result.text and scan_text(result.text, VENDOR_DETECTORS + EXTRA_VENDOR_DETECTORS):
        return SessionGitDiff(state="ok", path=result.path, sensitive=True, untracked=entry.kind == "untracked")
    return result


def read_file_diff(root: Path, entry: GitFile, *, staged: bool, unborn: bool) -> SessionGitDiff:
    rel = entry.path
    if rel.endswith("/"):
        return SessionGitDiff(state="ok", path=rel, directory=True, untracked=True)
    if is_secret_path(rel, entry.orig_path):
        return SessionGitDiff(state="ok", path=rel, sensitive=True, untracked=entry.kind == "untracked")
    if "\ufffd" in rel or (entry.orig_path and "\ufffd" in entry.orig_path):
        return SessionGitDiff(state="unknown", path=rel)
    _inside(root, rel)
    try:
        if entry.kind == "untracked":
            return _screened(_untracked(root, rel), entry)
        base = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M"]
        if unborn and not staged:
            empty = run_git(root, "hash-object", "-t", "tree", "/dev/null", timeout=TIMEOUT_S, untrusted_repo=True)
            if empty.returncode != 0 or not empty.stdout.strip():
                return SessionGitDiff(state="unknown", path=rel)
            base += [empty.stdout.strip()]
        else:
            base += ["--cached"] if staged or unborn else ["HEAD"]
        specs = [p for p in (entry.orig_path, rel) if p]
        done = run_git(root, *base, "--", *specs, timeout=TIMEOUT_S, optional_locks=False,
                       untrusted_repo=True, max_out=MAX_BYTES + 1)
    except subprocess.TimeoutExpired:
        log.warning("session_git_diff_timeout", path=rel)
        return SessionGitDiff(state="unknown", path=rel)
    except OSError as exc:
        log.warning("session_git_diff_failed", error=type(exc).__name__)
        return SessionGitDiff(state="unknown", path=rel)
    if done.returncode != 0:
        return SessionGitDiff(state="unknown", path=rel)
    if _BINARY_LINE.search(done.stdout) and "\n@@ " not in done.stdout:
        return SessionGitDiff(state="ok", path=rel, binary=True)
    text, truncated = _cap(done.stdout)
    return _screened(SessionGitDiff(state="ok", path=rel, text=text, truncated=truncated), entry)
