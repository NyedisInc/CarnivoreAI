
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

SHIMMED: List[str] = []

_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_SETSID_PY = '''import os, sys
args = sys.argv[1:]
fork = bool(args) and args[0] == "-f"
if fork:
    args = args[1:]
if fork or os.getpgrp() == os.getpid():
    pid = os.fork()
    if pid:
        if fork:
            os._exit(0)
        _p, status = os.waitpid(pid, 0)
        os._exit(os.waitstatus_to_exitcode(status))
os.setsid()
os.execvp(args[0], args)
'''
_FLOCK_PY = '''import fcntl, sys
fd = int(sys.argv[-1])
fcntl.flock(fd, fcntl.LOCK_EX)
'''


def _shim(directory: Path, name: str, source: str) -> None:
    py = directory / f"{name}.py"
    py.write_text(source, encoding="utf-8")
    stub = directory / name
    stub.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def far_shell() -> str:
    return shutil.which("dash", path=_SYSTEM_PATH) or "/bin/sh"


def far_path(home: Path, *, shims_on: bool = True) -> str:
    shims = home.parent / (home.name + "-shims")
    shims.mkdir(parents=True, exist_ok=True)
    SHIMMED.clear()
    for name, source in (("setsid", _SETSID_PY), ("flock", _FLOCK_PY)):
        if shims_on and shutil.which(name, path=_SYSTEM_PATH) is None:
            _shim(shims, name, source)
            SHIMMED.append(name)
    git = shutil.which("git")
    git_dir = [str(Path(git).parent)] if git and str(Path(git).parent) not in _SYSTEM_PATH.split(":") else []
    return ":".join([*([str(shims)] if shims_on else []), *git_dir, _SYSTEM_PATH])


def run(stdin: bytes, home: Path, *, noise: bytes = b"", timeout: float = 120.0, shell: Optional[str] = None,
        shims: bool = True) -> Tuple[int, bytes, bytes]:
    home.mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "USER": "farjob", "LOGNAME": "farjob", "SHELL": "/bin/sh", "LANG": "C", "PATH": far_path(home, shims_on=shims)}
    sh = shell or far_shell()
    argv = [sh, "-c", 'printf "%s" "$1"; exec "$2" -s', "sh", noise.decode("utf-8", "replace"), sh] if noise else [sh, "-s"]
    done = subprocess.run(argv, input=stdin, capture_output=True, env=env, cwd=str(home), timeout=timeout, check=False)
    return done.returncode, done.stdout, done.stderr


def kill_leftovers(home: Path) -> None:
    import signal

    for pid_file in (home / ".carnivore-ssh-jobs" / "meta").glob("*/*pid"):
        try:
            pid = int(pid_file.read_text().strip())
            os.killpg(pid, signal.SIGKILL)
        except (OSError, ValueError):
            continue
