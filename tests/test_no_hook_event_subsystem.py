
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nh_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nh_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import claude_hooks

SRC = ROOT / "src"

HOOK_PATH = "/hooks/claude-event"

ROUTE_DECORATOR = re.compile(
    r"@\w+\.(get|post|put|patch|delete|api_route|websocket)\s*\("
)

DELETED_MODULES = (
    "src/api/hook_event_routes.py",
    "src/api/hook_event_signals.py",
    "src/core/hook_toast_gate.py",
    "src/core/notifications/idle_watcher.py",
)


def _python_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 100, (
        f"only {len(files)} python files found under {SRC}; the scan below "
        f"would pass by looking at nothing"
    )
    return files


def test_no_module_declares_a_route_for_the_hook_event_path():
    scanned = 0
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if HOOK_PATH not in text:
            continue
        for line in text.splitlines():
            scanned += 1
            if HOOK_PATH in line and ROUTE_DECORATOR.search(line):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert offenders == [], (
        f"the hook event path {HOOK_PATH!r} is mounted again by "
        f"{offenders}; the endpoint was deleted on 2026-09-13 and the "
        f"session state now comes from src/core/attention/"
    )


def test_the_built_app_serves_no_hook_event_route():
    from src.main import app

    paths = [getattr(route, "path", "") for route in app.routes]
    assert len(paths) > 20, (
        f"the app exposes only {len(paths)} routes; this assertion would "
        f"pass by looking at nothing"
    )
    offenders = [path for path in paths if "hooks" in path]
    assert offenders == [], f"a hook route is mounted again: {offenders}"


@pytest.mark.parametrize("relative", DELETED_MODULES)
def test_the_deleted_modules_are_still_deleted(relative):
    assert not (ROOT / relative).exists(), (
        f"{relative} is back; it was deleted on 2026-09-13 with the rest "
        f"of the hook-event subsystem"
    )


def test_claude_hooks_exports_no_block_builder():
    for name in (
        "ensure_hook_settings",
        "_build_hook_block",
        "_build_managed_command",
        "_MANAGED_EVENTS",
    ):
        assert not hasattr(claude_hooks, name), (
            f"claude_hooks.{name} is back; hooks are never installed now, "
            f"and strip_managed_hooks only removes what an older build wrote"
        )
    assert hasattr(claude_hooks, "strip_managed_hooks"), (
        "strip_managed_hooks is gone, so an upgraded install would keep "
        "the block an older build wrote, forever"
    )


def test_the_session_manager_records_no_hook_events():
    from src.core.session_manager import SessionManager

    for name in (
        "record_hook_event",
        "subagent_depth",
        "subagent_wait_active",
        "should_suppress_idle_notification",
        "idle_watcher",
    ):
        assert not hasattr(SessionManager, name), (
            f"SessionManager.{name} is back; it was deleted on 2026-09-13 "
            f"with the hook-event subsystem"
        )
