
from __future__ import annotations

import asyncio
import contextlib
import http.server
import socket
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from textual.app import App

import src.tui.offline.launch as launch
from src.tui import __main__ as entry
from src.tui import attach
from src.tui.offline import app as offline_app
from src.tui.offline.app import OfflineTable, OfflineTui
from src.tui.offline.listing import OfflineRow
from src.tui.offline.names import offline_state_dir, read_names
from src.tui.offline.socket_check import OfflineContext
from src.tui.offline.tmux_cmd import TmuxCommandFailed, TmuxNotRunning, TmuxTarget

CONTEXT = OfflineContext(TmuxTarget("/opt/tmux", "/private/tmp/tmux-501/cloude"), "server")
ROWS = [
    OfflineRow("carnivore_live", 10, 0, dead=False, owned=True, display_name="Live one", project="Proj"),
    OfflineRow("cloude_husk", 11, 0, dead=True, owned=True),
]


def test_offline_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[attach.AttachPlan] = []
    shown_all: list[bool] = []

    def fake_rows(target: TmuxTarget, state_dir: Any, show_all: bool) -> list[OfflineRow]:
        shown_all.append(show_all)
        return ROWS

    monkeypatch.setattr(offline_app, "list_rows", fake_rows)
    monkeypatch.setattr(attach, "run", lambda plan: ran.append(plan) or 0)
    probed: list[tuple[str, ...]] = []
    monkeypatch.setattr(offline_app, "probe_session", lambda prefix, name, env=None: probed.append((name, len(ran))))
    monkeypatch.setattr(attach, "read_pane_size", lambda prefix, name: attach.PaneSize(200, 59, 1, "C-b"))
    monkeypatch.setenv("TMUX", "/private/tmp/tmux-501/cloude,1,0")
    monkeypatch.setattr(App, "suspend", lambda self: contextlib.nullcontext())

    async def run() -> None:
        app = OfflineTui(CONTEXT, None)
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            table = app.query_one(OfflineTable)
            assert table.row_count == 2
            assert [str(c) for c in table.get_row_at(0)] == ["Live one", "Proj", "carnivore_live", "running", "server down: read from tmux"]
            assert "dead pane" in str(table.get_row_at(1)[3])
            banner = str(app.query_one("#server-down-banner").render())
            assert "server down: read from tmux" in banner and "/private/tmp/tmux-501/cloude" in banner

            await pilot.press("w")
            watch = ran[-1]
            assert watch.suspend and "TMUX" not in watch.env
            assert watch.argvs[0][:6] == ("/opt/tmux", "-S", "/private/tmp/tmux-501/cloude", "-f", "/dev/null", "attach-session")
            assert "-r" in watch.argvs[0] and watch.argvs[0][-1] == "=carnivore_live"
            assert watch.preamble.startswith("\x1b[8;60;200t") and "read only" in watch.preamble

            await pilot.press("t")
            assert "-r" not in ran[-1].argvs[0] and "ignore-size" in ran[-1].argvs[0]

            await pilot.press("f", "enter")
            fit = ran[-1]
            assert "ignore-size" not in fit.argvs[0] and fit.argvs[0][-4:] == ("resize-window", "-A", "-t", "=carnivore_live:")
            assert "\x1b[" not in fit.preamble

            n = len(ran)
            await pilot.press("j", "w", "t")
            await pilot.pause()
            assert len(ran) == n
            assert probed and all(count == i for i, (_n, count) in enumerate(probed))

            await pilot.press("a")
            await pilot.pause()
            assert shown_all[0] is False and shown_all[-1] is True

    asyncio.run(run())


def test_offline_pilot_says_tmux_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def gone(*_a: Any) -> list[OfflineRow]:
        raise TmuxNotRunning("no server running")

    monkeypatch.setattr(offline_app, "list_rows", gone)

    async def run() -> str:
        app = OfflineTui(CONTEXT, None)
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            return str(app.query_one("#sessions-note").render())

    note = asyncio.run(run())
    assert "sessions are gone" in note and "reopen" in note


@pytest.fixture
def no_token_store(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    picked: list[str] = []

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("offline mode must never open tui_auth.json")

    monkeypatch.setattr("src.tui.token_store.TokenStore", boom)
    monkeypatch.setattr(launch, "run_offline", lambda settings_obj: picked.append("offline") or 0)
    return picked


def test_main_offline_flag_skips_probe_and_login(no_token_store: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "server_answers", lambda *_a, **_k: pytest.fail("probed"))
    assert entry.main(["--offline"]) == 0
    assert entry.main(["tui", "--offline"]) == 0
    assert no_token_store == ["offline", "offline"]


def test_main_goes_offline_when_server_silent(no_token_store: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "server_answers", lambda *_a, **_k: False)
    assert entry.main(["tui"]) == 0 and no_token_store == ["offline"]


@contextlib.contextmanager
def http_answering(status: int) -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_a: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_server_probe_down_only_without_an_answer() -> None:
    with http_answering(401) as url:
        assert launch.server_answers(url) is True
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    assert launch.server_answers(f"http://127.0.0.1:{port}") is False
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(1)
    try:
        assert launch.server_answers(f"http://127.0.0.1:{silent.getsockname()[1]}", timeout=0.2) is False
    finally:
        silent.close()


def _db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT);"
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, host_key TEXT, tmux_name TEXT, tmux_created_epoch INTEGER,"
        " tmux_socket TEXT, title TEXT, claude_title TEXT, project_id INTEGER, updated_at TEXT);"
        "INSERT INTO projects VALUES (1, 'Proj');"
        "INSERT INTO sessions VALUES (1, 'local', 'carnivore_a', 5, 'cloude', 'old name', NULL, 1, '2026-01-01');"
        "INSERT INTO sessions VALUES (2, 'local', 'carnivore_a', 10, 'cloude', '', 'claude says', 1, '2025-01-01');"
        "INSERT INTO sessions VALUES (3, 'peer-x', 'carnivore_b', 10, 'cloude', 'remote', NULL, 1, '2026-01-01');"
    )
    conn.commit()
    conn.close()


def test_names_join_read_only(tmp_path: Path) -> None:
    _db(tmp_path / "carnivore.db")
    names = read_names(tmp_path, "cloude", [("carnivore_a", 10), ("carnivore_b", 10)])
    assert names["carnivore_a"].display_name == "claude says" and names["carnivore_a"].project == "Proj"
    assert "carnivore_b" not in names
    empty = tmp_path / "empty"
    empty.mkdir()
    assert read_names(empty, "cloude", [("carnivore_a", 10)]) == {}
    assert list(empty.iterdir()) == []
    assert offline_state_dir(str(tmp_path / "absent")) is None and not (tmp_path / "absent").exists()


@pytest.mark.parametrize("failure", [TmuxNotRunning("no server running"), TmuxCommandFailed("can't find session")])
def test_failed_probe_means_no_attach_runs(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    ran: list[Any] = []
    told: list[str] = []

    def dead(*_a: Any, **_k: Any) -> None:
        raise failure

    monkeypatch.setattr(offline_app, "list_rows", lambda *_a: ROWS)
    monkeypatch.setattr(offline_app, "probe_session", dead)
    monkeypatch.setattr(attach, "run", lambda plan: ran.append(plan) or 0)
    monkeypatch.setattr(attach, "read_pane_size", lambda *_a: ran.append("size") or None)
    monkeypatch.setattr(App, "suspend", lambda self: contextlib.nullcontext())
    monkeypatch.setattr(OfflineTui, "notify", lambda self, msg, **_k: told.append(msg))

    async def run() -> None:
        app = OfflineTui(CONTEXT, None)
        async with app.run_test(size=(140, 30)) as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()

    asyncio.run(run())
    assert ran == [] and len(told) == 1
    if isinstance(failure, TmuxNotRunning):
        assert "sessions are gone" in told[0] and "reopen" in told[0]
