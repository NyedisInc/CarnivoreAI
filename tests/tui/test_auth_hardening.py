
from __future__ import annotations

import asyncio
import os
import stat
import threading
import time
from typing import Any
from pathlib import Path

import httpx
import pytest
from textual.worker import WorkerFailed

from src.tui.api_client import ApiClient, AuthRequired, ServerUnavailable
from src.tui.safe_errors import crash_summary
from src.tui.token_store import LockBusy, TokenPair, TokenStore
from tests.tui.test_auth import BASE, FakeServer, NoEvents, make_client, seed

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.planted-signature-value-0123456789"


def test_crash_summary_hides_locals_and_token_text() -> None:
    def inner() -> None:
        headers = {"Authorization": f"Bearer {FAKE_JWT}"}  # noqa: F841
        raise RuntimeError(f"upstream said Bearer {FAKE_JWT} code 654321")

    try:
        inner()
    except RuntimeError as exc:
        out = crash_summary(exc)
    assert "RuntimeError" in out and "test_auth_hardening.py" in out
    for secret in (FAKE_JWT, "planted-signature", "654321", "Authorization"):
        assert secret not in out


def test_unhandled_exception_in_the_app_prints_no_secret(tmp_path: Path) -> None:
    from src.tui.app import CarnivoreTui

    store = TokenStore(tmp_path)
    server = FakeServer()
    seed(store)

    async def run() -> str:
        app = CarnivoreTui(make_client(store, server), events=NoEvents())  # type: ignore[arg-type]
        shown: list = []
        app._print_error_renderables = lambda: shown.extend(app._exit_renderables)  # type: ignore[method-assign]
        secret_body = {"refresh_token": FAKE_JWT}

        async def crash() -> None:
            raise RuntimeError(f"boom {secret_body}")

        with pytest.raises(WorkerFailed):
            async with app.run_test() as pilot:
                await pilot.pause()
                app.run_worker(crash(), exit_on_error=True)
                await pilot.pause(0.3)
        return "\n".join(str(r) for r in shown)

    out = asyncio.run(run())
    assert "RuntimeError" in out and FAKE_JWT not in out and "planted-signature" not in out


def test_auth_required_after_startup_returns_to_login(tmp_path: Path) -> None:
    from src.tui.app import CarnivoreTui, LoginScreen, MainScreen

    store = TokenStore(tmp_path)
    server = FakeServer()
    seed(store)

    async def run() -> None:
        app = CarnivoreTui(make_client(store, server), events=NoEvents())  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert isinstance(app.screen, MainScreen)
            server.valid_access.clear()
            server.valid_refresh.clear()
            app.run_worker(app.client.request("GET", "/api/v1/auth/status"), exit_on_error=True)
            await pilot.pause(0.5)
            assert isinstance(app.screen, LoginScreen)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["symlink", "fifo", "group_readable", "world_readable"])
def test_unsafe_token_file_is_refused(tmp_path: Path, kind: str, caplog: pytest.LogCaptureFixture) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    good = store.path.read_bytes()
    if kind == "symlink":
        real = tmp_path / "real.json"
        real.write_bytes(good)
        real.chmod(0o600)
        store.path.unlink()
        store.path.symlink_to(real)
    elif kind == "fifo":
        store.path.unlink()
        os.mkfifo(store.path, 0o600)
    else:
        store.path.chmod(0o640 if kind == "group_readable" else 0o604)
    assert store.load() is None
    store.path.unlink()
    store.path.write_bytes(good)
    store.path.chmod(0o600)
    assert store.load() is not None


def test_other_owner_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(store.path).st_uid + 1)
    assert store.load() is None


def test_lock_file_symlink_is_refused_and_save_fsyncs_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = TokenStore(tmp_path)
    (tmp_path / "elsewhere").write_text("x")
    store.lock_path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        with store.locked():
            pass
    store.lock_path.unlink()
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(stat.S_IFMT(os.fstat(fd).st_mode)), real_fsync(fd))[1])
    seed(store)
    assert stat.S_IFDIR in synced


def test_lock_wait_is_bounded_and_reports_busy(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    with store.locked():
        t0 = time.monotonic()
        with pytest.raises(LockBusy):
            with TokenStore(tmp_path).locked(timeout=0.2):
                pass
        assert 0.15 < time.monotonic() - t0 < 2

        client = ApiClient(TokenStore(tmp_path), BASE)
        client._store.locked = lambda: TokenStore(tmp_path).locked(timeout=0.1)  # type: ignore[method-assign]

        async def run() -> None:
            with pytest.raises(ServerUnavailable):
                async with client._locked():
                    pass
            await client.aclose()

        asyncio.run(run())


def test_cancelled_acquire_releases_the_lock(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    client = ApiClient(store, BASE)

    async def run() -> None:
        holder = store.locked()
        holder.__enter__()
        kept: list[Any] = []
        real_locked = store.locked

        def keeping(*a: Any, **k: Any) -> Any:
            ctx = real_locked(*a, **k)
            kept.append(ctx)
            return ctx

        store.locked = keeping  # type: ignore[method-assign]
        task = asyncio.create_task(client._locked().__aenter__())
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        holder.__exit__(None, None, None)
        await asyncio.sleep(0.4)
        got = threading.Event()

        def probe() -> None:
            with TokenStore(tmp_path).locked(timeout=1.0):
                got.set()

        await asyncio.to_thread(probe)
        assert got.is_set()
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("path", ["http://evil.example/x", "//evil.example/x", "api/v1/x", "https://127.0.0.1/x", "", "/\t/evil"])
def test_request_refuses_paths_off_the_base(tmp_path: Path, path: str) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    client = ApiClient(store, BASE, transport=httpx.MockTransport(handler))

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.request("GET", path)
        await client.aclose()

    asyncio.run(run())
    assert seen == []


def test_refused_refresh_in_a_pane_reload_or_the_app_pump_returns_to_login(tmp_path: Path) -> None:
    from src.tui.app import CarnivoreTui, LoginScreen, MainScreen
    from src.tui.screens.ledger import LedgerPane

    def boom() -> None:
        raise AuthRequired()

    for trigger in ("reload", "pump"):
        store = TokenStore(tmp_path / trigger)
        server = FakeServer()
        seed(store)

        async def run() -> None:
            app = CarnivoreTui(make_client(store, server), events=NoEvents())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                assert isinstance(app.screen, MainScreen)
                if trigger == "reload":
                    server.valid_access.clear()
                    server.valid_refresh.clear()
                    pane = app.screen.query_one(LedgerPane)
                    pane.path = "/api/v1/auth/status"
                    await pane.reload()
                else:
                    app.call_later(boom)
                await asyncio.sleep(0.8)
                assert isinstance(app.screen, LoginScreen), trigger

        asyncio.run(run())
