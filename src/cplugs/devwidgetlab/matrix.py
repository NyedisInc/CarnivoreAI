
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.cplugs.devwidgetlab.capture import REPO, availability, repo_root
from src.cplugs.devwidgetlab.errors import CaptureBusy, CaptureUnavailable

logger = structlog.get_logger()

MATRIX_FOLDER = "matrix"
TABLE_FILE = "fit-table.json"
TIMEOUT_SECONDS = 4 * 3600

_job: Dict[str, Any] = {"task": None, "started": None, "exit": None, "reason": ""}


def matrix_dir(storage_path: Path) -> Path:
    return Path(storage_path) / MATRIX_FOLDER


def manifest_id(key: str) -> str:
    return key.split(":", 1)[0]


def command_for(out_dir: Path, catalog: bool, only: Optional[str] = None) -> list[str]:
    """The child process's argument list (no shell). Inputs: out_dir; catalog - also write catalog images; only - one widget's harness key. Output: argv.

    Example: command_for(out, False, "core.notes")  # [..., "--out", out, "--only", "core.notes"]
    """
    argv = [sys.executable, "-m", "scripts.widgets.gate", "--out", str(out_dir)]
    if only:
        argv += ["--only", manifest_id(only)]
    return argv + (["--catalog"] if catalog else [])


def read_table(storage_path: Path) -> Optional[Dict[str, Any]]:
    path = matrix_dir(storage_path) / TABLE_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("widget_lab_fit_table_unreadable", path=str(path), error=type(exc).__name__)
        return None


def state(storage_path: Path) -> Dict[str, Any]:
    """What the page shows: {available, reason, running, started, exit, table}. ``exit`` is the last run's status (0 clean, 1 failing, 2 cannot determine)."""
    task = _job["task"]
    return {**availability(), "running": bool(task and not task.done()), "started": _job["started"], "exit": _job["exit"],
            "table": read_table(storage_path)}


async def _run(argv: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(repo_root() or REPO), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), timeout=TIMEOUT_SECONDS)
        _job["exit"] = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        _job["exit"] = 2  # cannot determine
        logger.warning("widget_lab_matrix_timeout", seconds=TIMEOUT_SECONDS)


def start(storage_path: Path, catalog: bool = False, only: Optional[str] = None) -> Dict[str, Any]:
    status = availability()
    if not status["available"]:
        raise CaptureUnavailable(status["reason"])
    task = _job["task"]
    if task is not None and not task.done():
        raise CaptureBusy("a matrix run is already going")
    out = matrix_dir(storage_path)
    out.mkdir(parents=True, exist_ok=True)
    _job.update(task=asyncio.ensure_future(_run(command_for(out, catalog, only))), started=time.strftime("%Y-%m-%dT%H:%M:%S"), exit=None)
    return state(storage_path)
