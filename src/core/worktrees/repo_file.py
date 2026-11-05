from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.provider_ledger.refresh_poke import ENV_ALLOW_LIST

import structlog

logger = structlog.get_logger()

RELATIVE_PATH = os.path.join(".carnivore", "worktree.json")
MAX_FILE_BYTES = 1024 * 1024
SETUP_BUDGET_SECONDS = 600.0
OUTPUT_TAIL_BYTES = 64 * 1024

_SECRET_NAME = re.compile(r"(^|[/._-])(env|secrets?|credentials?|tokens?|keys?|pem|p8|p12|pfx|jks|keystore|id_rsa|id_ed25519"
                          r"|npmrc|netrc|pgpass|htpasswd|kubeconfig)([/._-]|$)"
                          r"|service[-_]?account", re.IGNORECASE)


class RepoFileRefused(ValueError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class RepoFile:

    sha256: str
    setup: Tuple[Tuple[str, ...], ...]
    copy: Tuple[str, ...]
    text: str


def looks_secret(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def read_repo_file(repo: str) -> Optional[RepoFile]:
    path = os.path.join(repo, RELATIVE_PATH)
    if not os.path.lexists(path):
        return None
    real_repo = os.path.realpath(repo)
    if os.path.islink(path) or not os.path.isfile(path) or os.path.dirname(os.path.realpath(path)) != os.path.join(
            real_repo, ".carnivore"):
        raise RepoFileRefused("repo_file_invalid", f"{RELATIVE_PATH} is not a plain file")
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise RepoFileRefused("repo_file_invalid", f"{RELATIVE_PATH} is over 1 MiB")
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepoFileRefused("repo_file_invalid", f"{RELATIVE_PATH} is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise RepoFileRefused("repo_file_invalid", f"{RELATIVE_PATH} must be an object")
    setup = data.get("setup", [])
    copy = data.get("copy", [])
    if not isinstance(setup, list) or not all(
            isinstance(step, list) and step and all(isinstance(a, str) and a for a in step) for step in setup):
        raise RepoFileRefused("repo_file_invalid", "setup must be a list of argument lists, e.g. [[\"npm\", \"ci\"]]")
    if not isinstance(copy, list) or not all(isinstance(c, str) and c for c in copy):
        raise RepoFileRefused("repo_file_invalid", "copy must be a list of file names")
    return RepoFile(sha256=hashlib.sha256(raw).hexdigest(), setup=tuple(tuple(s) for s in setup),
                    copy=tuple(copy), text=raw.decode("utf-8"))


def check_copy(repo: str, name: str) -> str:
    if os.path.isabs(name) or not name.strip():
        raise RepoFileRefused("copy_refused", f"{name!r} must be a path inside the repository")
    source = os.path.join(repo, name)
    if os.path.islink(source):
        raise RepoFileRefused("copy_refused", f"{name!r} is a symlink")
    real = os.path.realpath(source)
    if os.path.commonpath([real, repo]) != repo or real == repo:
        raise RepoFileRefused("copy_refused", f"{name!r} is outside the repository")
    if not os.path.isfile(real):
        raise RepoFileRefused("copy_refused", f"{name!r} is not a file in the repository")
    if os.path.getsize(real) > MAX_FILE_BYTES:
        raise RepoFileRefused("copy_refused", f"{name!r} is over 1 MiB")
    return real


def copy_files(repo: str, worktree: str, names: Sequence[str]) -> List[str]:
    plan = [(name, check_copy(repo, name)) for name in names]
    for name, source in plan:
        target = os.path.realpath(os.path.join(worktree, os.path.dirname(name)))
        if os.path.commonpath([target, worktree]) != worktree:
            raise RepoFileRefused("copy_refused", f"{name!r} would land outside the worktree")
        os.makedirs(target, exist_ok=True)
        destination = os.path.join(target, os.path.basename(name))
        if os.path.islink(destination):
            raise RepoFileRefused("copy_refused", f"{name!r} is a symlink in the worktree")
        shutil.copyfile(source, destination)
    return [name for name, _ in plan]


async def _read_tail(proc: "asyncio.subprocess.Process", tail: bytes) -> bytes:
    while True:
        chunk = await proc.stdout.read(65536)
        if not chunk:
            break
        tail = (tail + chunk)[-OUTPUT_TAIL_BYTES:]
    await proc.wait()
    return tail


def setup_env() -> Dict[str, str]:
    return {k: os.environ[k] for k in ENV_ALLOW_LIST if k in os.environ}


async def run_setup(steps: Sequence[Sequence[str]], cwd: str, *, budget: float = SETUP_BUDGET_SECONDS) -> str:
    deadline = time.monotonic() + budget
    tail = b""
    env = setup_env()
    for step in steps:
        try:
            proc = await asyncio.create_subprocess_exec(
                *step, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True, env=env)
        except OSError as exc:
            raise RepoFileRefused("setup_failed", f"{step[0]!r} could not start: {exc.strerror}") from None
        try:
            tail = await asyncio.wait_for(_read_tail(proc, tail), timeout=max(0.0, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            await proc.wait()
            raise RepoFileRefused("setup_timeout", "the setup ran past its 10-minute budget") from None
        if proc.returncode:
            text = tail.decode("utf-8", "replace")
            raise RepoFileRefused("setup_failed", f"{step[0]!r} exited {proc.returncode}:\n{text[-2000:]}")
    return tail.decode("utf-8", "replace")
