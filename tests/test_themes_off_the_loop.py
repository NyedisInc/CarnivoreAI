from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_themeloop_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_themeloop_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import src.api.themes_routes as themes_routes_mod


def _write_theme(root: Path, theme_id: str, *, with_effects: bool = False) -> None:
    theme_dir = root / theme_id
    theme_dir.mkdir(parents=True)
    manifest = {
        "id": theme_id,
        "name": theme_id.title(),
        "description": f"the {theme_id} theme",
        "cssVars": {"--x": "#000"},
    }
    if with_effects:
        manifest["effects"] = "effects.js"
        (theme_dir / "effects.js").write_text("export function init() {}\n", "utf-8")
    (theme_dir / "theme.json").write_text(json.dumps(manifest), "utf-8")


def _no_services_request() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


@pytest.fixture
def roots(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(themes_routes_mod, "_bundled_themes_root", lambda: bundled)
    monkeypatch.setattr(themes_routes_mod, "_user_themes_root", lambda: user)
    return bundled, user



def test_the_theme_scan_runs_off_the_event_loop(roots, monkeypatch):
    entered = threading.Event()
    released = threading.Event()

    def parked_scan(root, source):
        entered.set()
        if not released.wait(timeout=10.0):
            raise AssertionError(
                "the event loop never got to run while the theme scan was in "
                "progress: the scan is ON the loop"
            )
        return []

    monkeypatch.setattr(themes_routes_mod, "_scan_themes_root", parked_scan)

    async def scenario():
        task = asyncio.create_task(
            themes_routes_mod.list_themes(_no_services_request())
        )

        ticks = 0
        for _ in range(200):
            await asyncio.sleep(0.005)
            ticks += 1
            if entered.is_set():
                released.set()
                break
        return ticks, await task

    ticks, manifests = asyncio.run(scenario())
    assert entered.is_set(), "the scan never started"
    assert ticks > 0, "the loop was starved for the whole scan"
    assert manifests == []



def test_the_real_scan_and_its_digests_happen_in_a_worker_thread(roots):
    bundled, user = roots
    _write_theme(bundled, "aurora", with_effects=True)
    _write_theme(user, "neon", with_effects=True)

    scan_threads: list[int] = []
    real_scan = themes_routes_mod._scan_themes_root

    def recording_scan(root, source):
        scan_threads.append(threading.get_ident())
        return real_scan(root, source)

    themes_routes_mod._scan_themes_root = recording_scan
    try:
        async def scenario():
            return threading.get_ident(), await themes_routes_mod.list_themes(
                _no_services_request()
            )

        loop_thread, manifests = asyncio.run(scenario())
    finally:
        themes_routes_mod._scan_themes_root = real_scan

    assert len(scan_threads) == 2, "both roots should have been scanned"
    for ident in scan_threads:
        assert ident != loop_thread, (
            "the theme scan ran on the same thread as the event loop, so it "
            "is still blocking every terminal in the app"
        )
    assert [m.id for m in manifests] == ["aurora", "neon"]
    assert all(m.effectsDigest for m in manifests)



def test_the_loop_test_can_detect_a_scan_that_is_on_the_loop():
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.001)
            ticks += 1

    async def scenario():
        nonlocal ticks
        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        assert ticks > 0, "the heartbeat never started, so it proves nothing"
        before = ticks
        time.sleep(0.30)
        during = ticks - before
        hb.cancel()
        return during

    assert asyncio.run(scenario()) == 0, (
        "a synchronous 300ms call inside a coroutine let the loop run, so this "
        "harness cannot detect loop blocking and the tests above are worthless"
    )
