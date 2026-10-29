
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate.project_files import skipped_component
from src.cplugs.sdk import crate_format as cf

log = structlog.get_logger()

_PREFIX = ("--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "color.ui=false")
_DIFF_ARGS = ("diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color", "--relative", "--src-prefix=a/",
              "--dst-prefix=b/", "--submodule=short", "HEAD", "--", ".")
_FILTER_FIELDS = ("clean", "smudge", "process")


@dataclass(frozen=True)
class GitSnapshot:

    block: Dict[str, Any]
    patch: Optional[bytes]
    warnings: List[str] = field(default_factory=list)


def _env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    return env


def _run(git: str, root: str, args: Tuple[str, ...], limit: int, prefix: Tuple[str, ...] = _PREFIX) -> Tuple[int, bytes, bool]:
    proc = subprocess.Popen([git, *prefix, *args], cwd=root, env=_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timed_out = threading.Event()

    def expire() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(K.GIT_TIMEOUT_S, expire)
    timer.start()
    try:
        data = proc.stdout.read(limit + 1) if proc.stdout is not None else b""
        over = len(data) > limit
        if over:
            proc.kill()
        proc.wait()
    finally:
        timer.cancel()
        if proc.stdout is not None:
            proc.stdout.close()
    if timed_out.is_set():
        return -1, data[:limit], True
    return proc.returncode, data[:limit], over


def _filter_blanks(git: str, root: str) -> Tuple[str, ...]:
    rc, listing, _ = _run(git, root, ("config", "--list", "--includes", "-z"), K.GIT_STATUS_MAX_BYTES)
    if rc != 0:
        return ()
    names = set()
    for item in listing.split(b"\0"):
        key = item.split(b"\n", 1)[0].decode("utf-8", "replace").lower()
        if key.startswith("filter.") and key.rsplit(".", 1)[-1] in _FILTER_FIELDS + ("required",):
            names.add(key[len("filter."):key.rindex(".")])
    out: List[str] = []
    for name in sorted(names):
        for fld in _FILTER_FIELDS:
            out += ["-c", f"filter.{name}.{fld}="]
        out += ["-c", f"filter.{name}.required=false"]
    return tuple(out)


def _untracked(status: bytes, strip: str = "") -> Tuple[bool, List[str]]:
    parts = status.split(b"\0")
    dirty, untracked, index = False, [], 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            continue
        dirty = True
        code, path = entry[:2], entry[3:].decode("utf-8", "replace")
        if strip and path.startswith(strip):
            path = path[len(strip):]
        if code == b"??":
            untracked.append(path)
        elif b"R" in code or b"C" in code:
            index += 1
    return dirty, untracked


def snapshot(root: str) -> Optional[GitSnapshot]:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        if _run(git, root, ("rev-parse", "--is-inside-work-tree"), 16)[:2] != (0, b"true\n"):
            return None
        top_rc, top, _ = _run(git, root, ("rev-parse", "--show-toplevel"), 4096)
        prefix_rc, prefix, _ = _run(git, root, ("rev-parse", "--show-prefix"), 4096)
        if top_rc != 0 or prefix_rc != 0:
            return None
        strip = prefix.decode("utf-8", "replace").strip()
        if os.path.lexists(os.path.join(root, ".git")) and strip:
            return None
        opts = (*_PREFIX, *_filter_blanks(git, root))
        head_rc, head, _ = _run(git, root, ("rev-parse", "--verify", "-q", "HEAD"), 128, opts)
        branch_rc, branch, _ = _run(git, root, ("symbolic-ref", "--short", "-q", "HEAD"), 4096, opts)
        status_rc, status, status_cut = _run(git, root, ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."),
                                             K.GIT_STATUS_MAX_BYTES, opts)
        patch_rc, patch, patch_cut = ((-1, b"", False) if head_rc != 0 else
                                      _run(git, root, _DIFF_ARGS, K.PROJECT_PATCH_MAX_BYTES, opts))
    except OSError as exc:
        log.warning("crate_project_git_unavailable", error=type(exc).__name__)
        return None
    if status_rc != 0 and not status_cut:
        return None
    warnings: List[str] = []
    dirty, untracked = _untracked(status, strip)
    dirty = dirty or status_cut
    kept = [p for p in untracked if not skipped_component(p)]
    block: Dict[str, Any] = {
        "branch": branch.decode("utf-8", "replace").strip() if branch_rc == 0 else None, "detached": branch_rc != 0,
        "head": head.decode("ascii", "replace").strip() if head_rc == 0 else None, "dirty": dirty,
        "untracked": kept[:K.PROJECT_UNTRACKED_MAX], "untracked_count": len(kept),
        "untracked_truncated": status_cut or len(kept) > K.PROJECT_UNTRACKED_MAX,
        "patch_member": None, "patch_bytes": None}
    keep_patch: Optional[bytes] = None
    if head_rc == 0 and (patch_cut or patch_rc != 0):
        why = f"larger than {K.PROJECT_PATCH_MAX_BYTES} bytes or too slow" if patch_cut else "git diff failed"
        warnings.append(f"{K.W_PROJECT_PATCH}: the tracked changes could not be kept as a patch ({why}); the files "
                        "themselves are in the snapshot")
    elif head_rc == 0 and patch:
        keep_patch = patch
        block.update(patch_member=cf.constants.M_PROJECT_PATCH, patch_bytes=len(patch))
    return GitSnapshot(block, keep_patch, warnings)
