
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core.json_artifact import atomic_write_json
from src.core.pack.globalsync.store import Status

logger = structlog.get_logger()

INSTALL_TIMEOUT_SECONDS = 600.0
MAX_FOLDERS = 40
LOCKFILES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("package-lock.json", "npm", ("ci",)), ("npm-shrinkwrap.json", "npm", ("ci",)),
    ("pnpm-lock.yaml", "pnpm", ("install", "--frozen-lockfile")), ("yarn.lock", "yarn", ("install", "--frozen-lockfile")),
    ("bun.lock", "bun", ("install", "--frozen-lockfile")), ("bun.lockb", "bun", ("install", "--frozen-lockfile")))
FALLBACK = ("npm", ("install",))
INSTALLED, UNCHANGED, NEEDS_INSTALL, FAILED = "installed", "unchanged", "needs install", "failed"
_LOCK = threading.Lock()

Runner = Callable[[Sequence[str], str, float], int]


def run_command(cmd: Sequence[str], cwd: str, timeout: float) -> int:
    try:
        proc = subprocess.Popen(list(cmd), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return 127
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
        return -1


class InstallState:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        keys = raw.get("keys") if isinstance(raw, dict) else None
        return {k: v for k, v in keys.items() if isinstance(v, str)} if isinstance(keys, dict) else {}

    def save(self, keys: Dict[str, str]) -> bool:
        return atomic_write_json(self.path, {"v": 1, "keys": keys}, log_event="pack_global_install_state_write_failed")


def plan(target: Path, owned: Iterable[str]) -> List[Path]:
    found: List[Path] = []
    for rel in sorted(owned):
        if rel.rsplit("/", 1)[-1] != "package.json" or len(found) >= MAX_FOLDERS:
            continue
        try:
            declared = json.loads((target / rel).read_text(encoding="utf-8")).get("dependencies")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(declared, dict) and declared:
            found.append((target / rel).parent)
    return found


def command_for(folder: Path) -> Tuple[str, Tuple[str, ...], str]:
    for name, tool, args in LOCKFILES:
        if (folder / name).is_file():
            return tool, args, hashlib.sha256((folder / name).read_bytes()).hexdigest()
    return (*FALLBACK, hashlib.sha256((folder / "package.json").read_bytes()).hexdigest())


def install_folders(folders: Sequence[Path], state: InstallState, status: Status, *, runner: Runner = run_command,
                    which: Callable[[str], Optional[str]] = shutil.which, timeout: float = INSTALL_TIMEOUT_SECONDS) -> Dict[str, str]:
    results: Dict[str, str] = {}
    with _LOCK:
        keys = state.load()
        for folder in folders:
            name = str(folder)
            try:
                tool, args, key = command_for(folder)
            except OSError:
                continue
            has_modules = (folder / "node_modules").is_dir()
            if has_modules and name not in keys:
                keys[name] = key
            if has_modules and keys.get(name) == key:
                results[name] = UNCHANGED
                continue
            path = which(tool)
            if path is None:
                results[name] = NEEDS_INSTALL
                status.record(name, NEEDS_INSTALL, tool=tool)
                logger.info("pack_global_install_tool_missing", tool=tool)
                continue
            code = runner([path, *args], name, timeout)
            keys[name] = key if code == 0 else f"failed:{key}"
            results[name] = INSTALLED if code == 0 else FAILED
            status.record(name, results[name], tool=tool, **({} if code == 0 else {"exit": code}))
            logger.info("pack_global_install", tool=tool, state=results[name], exit=code)
        state.save(keys)
    return results


def install_applied(targets: Sequence[Tuple[Path, Sequence[str]]], state: InstallState, status: Status, **kwargs) -> Dict[str, str]:
    folders = [f for target, owned in targets for f in plan(target, owned)]
    return install_folders(folders, state, status, **kwargs) if folders else {}
