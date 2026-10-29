
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from src.api.request_log import RequestLogMiddleware
from src.core.perf_hooks import monitor as monitor_module
from src.core.perf_hooks.monitor import FRAME_TYPE, PerfMonitor, frame_topic
from src.core.perf_hooks.process_stats import parse_ps, tmux_servers


class _FakeSampler:

    def __init__(self) -> None:
        self.calls = 0

    def sample(self) -> Dict[str, object]:
        self.calls += 1
        return {"server": {"pid": 1, "cpu_pct": 1.5, "rss_mb": 100.0}, "tmux": {}}


async def _asgi_ok(scope: Dict[str, Any], receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


async def _one_request(path: str) -> None:
    async def receive() -> Dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: Dict[str, Any]) -> None:
        return None

    scope = {"type": "http", "method": "GET", "path": path, "client": ("127.0.0.1", 1)}
    await RequestLogMiddleware(_asgi_ok)(scope, receive, send)


def _counters_empty(m: PerfMonitor) -> bool:
    return all(not b.routes and not b.ws and not b.lag_ms and not b.watcher_ms for b in m._buckets)


def test_off_records_nothing_runs_nothing_publishes_nothing(monkeypatch) -> None:
    sampler = _FakeSampler()
    m = PerfMonitor(sampler=sampler)
    monkeypatch.setattr(monitor_module, "PERF", m)
    monkeypatch.setattr("src.api.request_log.PERF", m)
    published: List[Dict[str, Any]] = []

    async def scenario() -> None:
        await _one_request("/api/v1/sessions/list")
        m.record_request("GET", "/api/v1/sessions/list", 5.0)
        m.record_ws("events", "stats.changed", 70, "evt_1")
        m.record_watcher_pass(0.01, "full")
        time.sleep(0.05)
        await asyncio.sleep(0.2)
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "perf-hooks"]

    asyncio.run(scenario())
    assert m.enabled is False
    assert m._task is None
    assert _counters_empty(m)
    assert m.last_frame is None
    assert sampler.calls == 0
    assert published == []


def test_on_reports_loop_lag_requests_sockets_and_processes(monkeypatch) -> None:
    sampler = _FakeSampler()
    m = PerfMonitor(sampler=sampler)
    monkeypatch.setattr("src.api.request_log.PERF", m)
    published: List[Dict[str, Any]] = []

    async def scenario() -> Dict[str, Any]:
        m.enable(lambda frame: published.append(frame) or 1)
        await asyncio.sleep(0.15)
        time.sleep(0.25)
        await asyncio.sleep(0.15)
        for _ in range(3):
            await _one_request("/api/v1/sessions/list")
        m.record_ws("events", frame_topic('{"type": "stats.changed"}'), 26, "evt_1")
        m.record_ws("terminal_in", "pty_input", 1, "ses_1")
        m.record_watcher_pass(0.012, "full")
        frame = await m.publish_now()
        m.disable()
        await asyncio.sleep(0)
        return frame

    frame = asyncio.run(scenario())
    assert published and published[-1] is frame
    assert frame["type"] == FRAME_TYPE
    assert frame["loop_lag_ms"]["max"] >= 100.0
    assert frame["loop_lag_ms"]["stalls_per_min"] > 0
    routes = {(r["method"], r["route"]): r for r in frame["routes"]}
    assert ("GET", "/api/v1/sessions/list") in routes
    assert frame["requests_per_min"] > 0
    topics = {(w["channel"], w["topic"]) for w in frame["ws"]}
    assert ("events", "stats.changed") in topics and ("terminal_in", "pty_input") in topics
    assert frame["watcher_ms"]["full"]["p50"] >= 12.0
    assert frame["processes"]["server"]["rss_mb"] == 100.0
    assert m.enabled is False and m._task is None and _counters_empty(m)


def test_process_parsing_finds_tmux_servers_by_socket() -> None:
    rows = parse_ps(
        "  10     1   1:02.50  2048 /opt/homebrew/bin/tmux -L cloude -f x new-session -d\n"
        "  11    10   0:00.01   512 /opt/homebrew/bin/tmux -L cloude send-keys -l x\n"
        "  12     1   0:00.10  1024 /usr/bin/python3 -m src.main\n"
        "garbage line\n"
    )
    assert len(rows) == 3 and rows[0].cpu_seconds == 62.5
    servers = tmux_servers(rows)
    assert list(servers) == ["cloude"] and servers["cloude"].pid == 10
    assert frame_topic('{"no_type": 1}') == "text"
