
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Dict, Optional

import structlog

from src.config.agent_command import claude_cli_path
from src.config.launch_profiles import LaunchProfile

logger = structlog.get_logger()

CHECK_TIMEOUT_SECONDS = 5.0

_ENV_KEEP = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR")

_OUTPUT_CHARS = 300


def harness_binary(harness: str) -> Optional[str]:
    """The binary a harness launches, or None when it has no known one (or is not installed).

    Example: harness_binary("shell") -> "/bin/zsh"
    """
    if harness == "claude":
        found = claude_cli_path(None)
        return found if shutil.which(found) or os.path.isabs(found) else None
    if harness == "codex":
        return shutil.which("codex")
    if harness == "shell":
        return shutil.which("zsh") or "/bin/zsh"
    return None


def scrubbed_env() -> Dict[str, str]:
    env = {name: os.environ[name] for name in _ENV_KEEP if name in os.environ}
    env["TERM"] = "dumb"
    return env


async def run_check(profile: LaunchProfile) -> Dict[str, Any]:
    if profile.harness not in ("claude", "codex", "shell"):
        return {"status": "not_checkable", "binary": None, "output": f"{profile.harness} has no known binary", "exit_code": None}
    binary = harness_binary(profile.harness)
    if binary is None:
        return {"status": "missing", "binary": None, "output": f"{profile.harness} is not installed", "exit_code": None}
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--version", env=scrubbed_env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        return {"status": "missing", "binary": binary, "output": f"could not start: {exc.strerror or exc}", "exit_code": None}
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), CHECK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"status": "timeout", "binary": binary, "output": f"no answer in {int(CHECK_TIMEOUT_SECONDS)} seconds", "exit_code": None}
    text = out.decode("utf-8", "replace").strip()[:_OUTPUT_CHARS]
    status = "ok" if proc.returncode == 0 else "failed"
    logger.info("launch_profile_check", profile_id=profile.id, harness=profile.harness, status=status)
    return {"status": status, "binary": binary, "output": text, "exit_code": proc.returncode}
