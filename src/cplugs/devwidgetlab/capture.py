
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.cplugs.devwidgetlab.errors import CaptureBusy, CaptureTimeout, CaptureUnavailable

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "widgets" / "capture_one.py"
CAPTURES_FOLDER = "captures"
TIMEOUT_SECONDS = 900
EXIT_CLEAN, EXIT_FAILED, EXIT_CANNOT_DETERMINE = 0, 1, 2
HOSTS = ("home", "terminal", "drawer", "popout")
FIXTURES = ("data", "empty", "stress")
STATES = ("normal", "menu")
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,79}$")
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MAX_SCENARIO_CHARS = 200_000

_running = asyncio.Lock()


def repo_root() -> Optional[Path]:
    from src.cplugs.devwidgetlab.drafts import checkout  # noqa: PLC0415

    return checkout.resolve()


def availability() -> Dict[str, Any]:
    if repo_root() is None:
        return {"available": False, "reason": "no_checkout"}
    if importlib.util.find_spec("playwright") is None:
        return {"available": False, "reason": "no_playwright"}
    return {"available": True, "reason": ""}


def captures_dir(storage_path: Path) -> Path:
    return Path(storage_path) / CAPTURES_FOLDER


def command_for(request: Dict[str, Any], out_dir: Path, scenario_file: Optional[Path]) -> list[str]:
    args = [sys.executable, "-m", "scripts.widgets.capture_one", "--widget", request["widget"], "--host", request["host"],
            "--size", request["size"], "--theme", request["theme"], "--fixture", request["fixture"],
            "--state", request["state"], "--out", str(out_dir)]
    if scenario_file is not None:
        args += ["--scenario-file", str(scenario_file)]
    sidebar = request.get("sidebar")
    if sidebar is not None:
        args += ["--sidebar", "--width", sidebar["width"], "--area", sidebar["area"], "--density", sidebar["density"]]
        if sidebar["folded"]:
            args.append("--folded")
    return args


def result_from(stdout: str, code: int, stderr: str) -> Dict[str, Any]:
    if code == EXIT_CANNOT_DETERMINE:
        return {"ok": False, "determined": False, "failures": [stderr.strip().splitlines()[-1] if stderr.strip() else "the capture could not run"]}
    try:
        meta = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "determined": False, "failures": ["the capture printed no result"]}
    meta["determined"] = True
    meta["ok"] = bool(meta.get("ok")) and code == EXIT_CLEAN
    return meta


async def run_capture(request: Dict[str, Any], storage_path: Path) -> Dict[str, Any]:
    status = availability()
    if not status["available"]:
        raise CaptureUnavailable(status["reason"])
    if _running.locked():
        raise CaptureBusy("a capture is already running")
    async with _running:
        out_dir = captures_dir(storage_path) / time.strftime("%Y%m%d-%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        scenario_file: Optional[Path] = None
        if request.get("scenario") is not None:
            scenario_file = out_dir / "scenario.json"
            scenario_file.write_text(request["scenario"], encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(*command_for(request, out_dir, scenario_file), cwd=str(repo_root() or REPO),
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CaptureTimeout(f"the capture took longer than {TIMEOUT_SECONDS} seconds") from None
        return result_from(stdout.decode("utf-8", "replace"), proc.returncode or 0, stderr.decode("utf-8", "replace"))
