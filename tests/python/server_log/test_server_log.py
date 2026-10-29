
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import server_log_routes
from src.api.auth import require_auth
from src.core.resource_push.topics import RESOURCE_TOPICS, SERVER_LOG
from src.core.server_log import ServerLogWatch, read_entries
from src.core.server_log import tail as tail_module
from src.core.server_log import watch as watch_module


def _line(event: str, level: str = "info", **fields) -> str:
    return "[STDOUT] " + json.dumps({"event": event, "timestamp": "2026-10-15T19:00:00Z", "level": level, **fields})


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n")
    return path


def test_parses_levels_fields_and_skips_malformed(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [
        _line("a", "warning", session="ses_1", n=3),
        "[STDERR] Traceback (most recent call last):",
        "[STDOUT] {not json",
        '[STDOUT] {"no_event": 1}',
        _line("b", "debug"),
        _line("c", "critical"),
    ])
    got = read_entries(log)
    assert [(e["event"], e["level"]) for e in got] == [("a", "warn"), ("b", "debug"), ("c", "error")]
    assert got[0]["fields"] == "session=ses_1 n=3"
    assert [e["event"] for e in read_entries(log, ["error"])] == ["c"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_entries(tmp_path / "nope.log") == []


def test_limit_applies_after_level_filter(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line(f"e{i}", "error" if i % 10 == 0 else "info") for i in range(100)])
    assert [e["event"] for e in read_entries(log, ["error"], 3)] == ["e70", "e80", "e90"]


def test_secret_is_redacted_everywhere(tmp_path: Path) -> None:
    token = "ghp_" + "a1B2c3D4e5" * 3 + "abcdef"
    log = _write(tmp_path / "server.log", [_line(f"leak {token}", "error", detail=f"auth {token}")])
    entry = read_entries(log)[0]
    assert token not in entry["event"] and token not in entry["fields"]
    assert "*" in entry["event"]


def test_read_is_bounded_on_a_big_file(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "server.log"
    with log.open("w") as handle:
        for i in range(60000):
            handle.write(_line(f"event{i}", pad="x" * 40) + "\n")
    assert log.stat().st_size > 1024 * 1024
    monkeypatch.setattr(tail_module, "MAX_BYTES", 64 * 1024)
    seen: list[int] = []
    real = tail_module.read_tail_bytes

    def spy(path, max_bytes):
        data = real(path, max_bytes)
        seen.append(len(data))
        return data

    monkeypatch.setattr(tail_module, "read_tail_bytes", spy)
    got = read_entries(log, limit=10**6)
    assert seen and seen[0] <= 64 * 1024
    assert len(got) <= tail_module.MAX_LINES
    assert got[-1]["event"] == "event59999"
    assert all(e["event"].startswith("event") for e in got)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(server_log_routes.router, prefix="/api/v1")
    return app


def test_route_requires_auth_leases_and_reads(tmp_path: Path, monkeypatch) -> None:
    log = _write(tmp_path / "server.log", [_line("one"), _line("two", "error")])
    monkeypatch.setattr(server_log_routes, "server_log_path", lambda: log)
    app = _app()
    with TestClient(app) as http:
        assert http.get("/api/v1/server-log").status_code in (401, 403)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as http:
        body = http.get("/api/v1/server-log?levels=error").json()
        assert [e["event"] for e in body["entries"]] == ["two"]
        assert body["levels"] == ["error", "warn", "info", "debug"]
        assert app.state.server_log_watch.running
        assert http.get("/api/v1/server-log?levels=nope").status_code == 422
        assert http.get("/api/v1/server-log?limit=501").status_code == 422
        assert http.get("/api/v1/server-log?path=/etc/passwd").json()["entries"]
    assert SERVER_LOG in RESOURCE_TOPICS


@pytest.mark.asyncio
async def test_watch_is_viewer_gated_and_names_only_on_change(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line("a")])
    now = [0.0]
    named: list[str] = []

    async def sleep(seconds: float) -> None:
        now[0] += seconds
        if len(named) == 0 and now[0] == 3.0:
            log.write_text(log.read_text() + _line("b") + "\n")
        await asyncio.sleep(0)

    watch = ServerLogWatch(lambda: log, notify=named.append, sleep=sleep, clock=lambda: now[0])
    assert not watch.running
    watch.touch()
    task = watch._task
    watch._lease_until = 8.0
    await task
    assert named[0] == SERVER_LOG
    assert named.count(SERVER_LOG) == 1
    assert not watch.running


@pytest.mark.asyncio
async def test_watch_keepalive_and_stop(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line("a")])
    now = [0.0]
    named: list[str] = []

    async def sleep(seconds: float) -> None:
        now[0] += seconds
        await asyncio.sleep(0)

    watch = ServerLogWatch(lambda: log, notify=named.append, sleep=sleep, clock=lambda: now[0])
    watch.touch()
    task = watch._task
    watch._lease_until = watch_module.KEEPALIVE_SECONDS + 2
    await task
    assert named == [SERVER_LOG]
    await watch.stop()


def test_a_token_ending_one_entry_does_not_star_the_next_entrys_event(tmp_path: Path) -> None:
    token = "sk-ant-api03-" + "A" * 60
    log = _write(tmp_path / "server.log", [_line("first", key=token), _line("second_event_name")])
    entries = read_entries(log)
    assert [e["event"] for e in entries] == ["first", "second_event_name"]
    assert token not in entries[0]["fields"]
