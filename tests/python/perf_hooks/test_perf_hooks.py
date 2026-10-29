
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from src.api.request_log import RequestLogMiddleware
from src.core.perf_hooks import monitor as monitor_module
from src.core.perf_hooks.monitor import FRAME_TYPE, PerfMonitor, frame_topic
from src.core.perf_hooks.process_stats import ProcessSampler, parse_ps, tmux_servers


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


def test_sampler_reports_shell_roles_and_window_server(monkeypatch) -> None:
    app = "/Applications/Carnivore.app/Contents"
    def ps(main_cpu: str, rend_cpu: str, gpu_cpu: str, ws_cpu: str) -> str:
        return (
            f"  20     1   {main_cpu}  102400 {app}/MacOS/Carnivore\n"
            f"  21    20   {rend_cpu}  204800 {app}/Frameworks/Carnivore Helper (Renderer).app/Contents/MacOS/Carnivore Helper (Renderer) --type=renderer --lang=en\n"
            f"  22    20   {gpu_cpu}   51200 {app}/Frameworks/Carnivore Helper (GPU).app/Contents/MacOS/Carnivore Helper (GPU) --type=gpu-process\n"
            f"  23    20   0:00.10   10240 {app}/Frameworks/Carnivore Helper.app/Contents/MacOS/Carnivore Helper --type=utility\n"
            "  30     1   0:50.00   99999 /Applications/Slack.app/Contents/Frameworks/Slack Helper (Renderer).app/Contents/MacOS/Slack Helper (Renderer) --type=renderer\n"
            f"  40     1   {ws_cpu}   30720 /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer -daemon\n"
        )
    clock = iter([100.0, 110.0])
    monkeypatch.setattr("src.core.perf_hooks.process_stats.time.monotonic", lambda: next(clock))
    sampler = ProcessSampler(own_pid=999)
    first = sampler.sample(parse_ps(ps("0:10.00", "1:00.00", "0:20.00", "5:00.00")))
    assert first["shell"]["main"]["cpu_pct"] is None and first["window_server"]["cpu_pct"] is None
    second = sampler.sample(parse_ps(ps("0:11.00", "1:05.00", "0:20.50", "5:02.00")))
    shell = second["shell"]
    assert shell["main"] == {"pid": 20, "cpu_pct": 10.0, "rss_mb": 100.0}
    assert shell["renderer"] == [{"pid": 21, "cpu_pct": 50.0, "rss_mb": 200.0}]
    assert shell["gpu"] == {"pid": 22, "cpu_pct": 5.0, "rss_mb": 50.0}
    assert [u["pid"] for u in shell["utility"]] == [23]
    assert second["window_server"] == {"pid": 40, "cpu_pct": 20.0, "rss_mb": 30.0}
    assert 30 not in {shell["main"]["pid"], shell["gpu"]["pid"], *(r["pid"] for r in shell["renderer"])}
