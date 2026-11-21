
from __future__ import annotations

import asyncio
import hashlib
import os
import posixpath
import pwd
import signal
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

import structlog

from src.core.pack.jobs import paths
from src.core.pack.jobs.types import DepDir

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Step:

    cwd: str
    argv: List[str]
    memo_key: str
    memo_value: str


@dataclass
class RecipeResult:

    ok: bool
    failed_step: Optional[int]
    seconds: float
    memo: Dict[str, str] = field(default_factory=dict)


def login_shell() -> str:
    shell = os.environ.get("SHELL")
    if shell:
        return shell
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/zsh"
    except KeyError:
        return "/bin/zsh"


def plan(slot_path: str, dep_dirs: Sequence[DepDir], memo: Mapping[str, str], override: Optional[Sequence[str]], *,
         air_gap: bool = False, shell: Optional[str] = None) -> List[Step]:
    if override is not None:
        shell = shell or login_shell()
        return [Step(slot_path, [shell, "-l", "-c", text], "override", hashlib.sha256(f"{i}:{text}".encode()).hexdigest())
                for i, text in enumerate(override)]
    steps: List[Step] = []
    if air_gap:
        return steps
    for dep in dep_dirs:
        digest = hashlib.sha256("\n".join(sorted(dep.locks.values())).encode()).hexdigest()
        if memo.get(dep.path) == digest:
            continue
        parent_rel, name = posixpath.split(dep.path)
        cwd = str(Path(slot_path, parent_rel)) if parent_rel else slot_path
        if dep.kind == "npm":
            steps.append(Step(cwd, ["npm", "ci"], dep.path, digest))
            continue
        py = f"python{dep.python}" if dep.python else "python3"
        steps.append(Step(cwd, [py, "-m", "venv", name], dep.path, digest))
        for lock in sorted(dep.locks):
            steps.append(Step(cwd, [f"{name}/bin/pip", "install", "-r", posixpath.relpath(lock, parent_rel or ".")], dep.path, digest))
        vpy = shlex.quote(f"{name}/bin/python")
        steps.append(Step(cwd, ["sh", "-c", f"if {vpy} -c 'import playwright' 2>/dev/null; then {vpy} -m playwright install chromium; fi"],
                          dep.path, digest))
    return steps


def _kill_group(proc: "asyncio.subprocess.Process") -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def run(steps: Sequence[Step], log_path: Path, *, shell: Optional[str] = None, timeout_s: float = 1800) -> RecipeResult:
    shell = shell or login_shell()
    env = paths.clean_env()
    started = time.monotonic()
    remaining = {s.memo_key: sum(1 for t in steps if t.memo_key == s.memo_key) for s in steps}
    memo: Dict[str, str] = {}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as sink:
        for i, step in enumerate(steps):
            left = timeout_s - (time.monotonic() - started)
            code: Optional[int] = None
            if left > 0:
                proc = await asyncio.create_subprocess_exec(shell, "-l", "-c", shlex.join(step.argv), cwd=step.cwd, env=env,
                                                            stdin=asyncio.subprocess.DEVNULL, stdout=sink, stderr=asyncio.subprocess.STDOUT,
                                                            start_new_session=True)
                try:
                    code = await asyncio.wait_for(proc.wait(), left)
                except asyncio.TimeoutError:
                    _kill_group(proc)
                    await proc.wait()
                except asyncio.CancelledError:
                    _kill_group(proc)
                    await proc.wait()
                    raise
            if code != 0:
                log.warning("pack_job_recipe_step_failed", step=i, code=code)
                return RecipeResult(False, i, time.monotonic() - started, memo)
            remaining[step.memo_key] -= 1
            if remaining[step.memo_key] == 0:
                memo[step.memo_key] = step.memo_value
    return RecipeResult(True, None, time.monotonic() - started, memo)
