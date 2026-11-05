
from __future__ import annotations

import asyncio
import plistlib
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger()

LAUNCH_SERVICES_PLIST = (Path.home() / "Library" / "Preferences" / "com.apple.LaunchServices"
                         / "com.apple.launchservices.secure.plist")

FALLBACK_BROWSER = "com.apple.Safari"

OPEN_TIMEOUT_SECONDS = 10.0


class OpenFailed(Exception):
    pass


def default_browser(plist_path: Path = LAUNCH_SERVICES_PLIST) -> str:
    try:
        with plist_path.open("rb") as handle:
            handlers = plistlib.load(handle).get("LSHandlers", [])
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        logger.debug("default_browser_unreadable", error=str(exc))
        return FALLBACK_BROWSER
    for scheme in ("https", "http"):
        for row in handlers:
            if isinstance(row, dict) and row.get("LSHandlerURLScheme") == scheme:
                bundle = row.get("LSHandlerRoleAll")
                if isinstance(bundle, str) and bundle:
                    return bundle
    return FALLBACK_BROWSER


def open_argv(path: str, app: str, browser: Optional[str] = None) -> list[str]:
    if not path.startswith("/"):
        raise ValueError("path must be absolute")
    if app == "finder":
        return ["open", "-R", path]
    return ["open", "-b", browser or default_browser(), path]


async def _run(argv: list[str]) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=OPEN_TIMEOUT_SECONDS)
    except (OSError, asyncio.TimeoutError) as exc:
        raise OpenFailed(f"could not run open: {exc}") from exc
    if proc.returncode != 0:
        raise OpenFailed(err.decode("utf-8", errors="replace").strip() or f"open answered {proc.returncode}")


Runner = Callable[[list[str]], Awaitable[None]]
run_open: Runner = _run


async def open_path(path: str, app: str) -> None:
    if sys.platform != "darwin":
        raise OpenFailed("this computer has no finder")
    await run_open(open_argv(path, app))
    logger.info("terminal_path_opened", app=app)
