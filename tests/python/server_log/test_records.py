
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import server_log_routes
from src.api.auth import require_auth
from src.core.server_log import records as records_module
from src.core.server_log.records import MAX_CONTINUATION_LINES, group, parse_cursor, read_page

TOKEN = "ghp_" + "a1B2c3D4e5" * 3 + "abcdef"


def _line(event: str, level: str = "info", **fields) -> str:
    return "[STDOUT] " + json.dumps({"event": event, "timestamp": "2026-10-16T10:00:00Z", "level": level, **fields})


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n")
    return path


def test_traceback_opens_a_record_and_stderr_continues(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [
        _line("a", "warning", session="ses_1", n=3),
        "[STDERR] some stderr text",
        "[STDERR] Traceback (most recent call last):",
        '[STDERR]   File "x.py", line 1, in <module>',
        "[STDERR] ValueError: boom",
        _line("b"),
    ])
    page = read_page(log)
    got = page["records"]
    assert [(r["event"], r["level"], r["source"]) for r in got] == [
        ("a", "warn", "server"),
        ("ValueError: boom", "error", "stderr"),
        ("b", "info", "server"),
    ]
    assert got[0]["fields"] == {"session": "ses_1", "n": "3"}
    assert got[0]["lines"] == ["some stderr text"] and not got[0]["traceback"]
    assert got[1]["lines"] == ["Traceback (most recent call last):", '  File "x.py", line 1, in <module>', "ValueError: boom"]
    assert got[1]["traceback"] and not got[1]["continues"]


def test_leading_orphan_is_an_error_record_marked_continues() -> None:
    drafts = group([(1, 0, "[STDERR] tail of something"), (1, 30, "more")])
    assert len(drafts) == 1 and drafts[0].level == "error" and drafts[0].continues
    assert drafts[0].lines == ["more"]


def test_continuation_is_bounded() -> None:
    lines = [(1, 0, '{"event": "x", "level": "error"}')] + [(1, i + 40, f"line {i}") for i in range(MAX_CONTINUATION_LINES + 5)]
    draft = group(lines)[0]
    assert len(draft.lines) == MAX_CONTINUATION_LINES and draft.dropped == 5


def test_every_value_is_redacted(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line(f"leak {TOKEN}", "error", detail=f"auth {TOKEN}"), f"[STDERR] key={TOKEN}"])
    record = read_page(log)["records"][0]
    text = json.dumps(record)
    assert TOKEN not in text and "*" in record["fields"]["detail"]


def test_head_resumes_and_skips_a_half_written_line(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text(_line("one") + "\n" + '[STDOUT] {"event": "tw')
    first = read_page(log)
    assert [r["event"] for r in first["records"]] == ["one"]
    with log.open("a") as handle:
        handle.write('o", "level": "info"}\n' + _line("three") + "\n")
    delta = read_page(log, since=parse_cursor(first["head"]))
    assert [r["event"] for r in delta["records"]] == ["two", "three"]
    assert read_page(log, since=parse_cursor(delta["head"]))["records"] == []


def test_since_follows_a_rotation(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line("old1")])
    head = read_page(log)["head"]
    with log.open("a") as handle:
        handle.write(_line("old2") + "\n")
    log.rename(tmp_path / "server.log.1")
    _write(log, [_line("new1")])
    page = read_page(log, since=parse_cursor(head))
    assert [r["event"] for r in page["records"]] == ["old2", "new1"] and not page["reset"]


def test_unknown_cursor_resets_and_gap_is_flagged(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_line(f"e{i}", pad="x" * 50) for i in range(200)])
    reset = read_page(log, since=parse_cursor("1-0"))
    assert reset["reset"] and reset["records"][-1]["event"] == "e199"
    head = read_page(log)["head"]
    with log.open("a") as handle:
        for i in range(200):
            handle.write(_line(f"n{i}", pad="x" * 50) + "\n")
    gap = read_page(log, since=parse_cursor(head), max_bytes=4096)
    assert gap["gap"] and gap["records"][-1]["event"] == "n199"


def test_paging_back_walks_into_the_rotated_file(tmp_path: Path) -> None:
    _write(tmp_path / "server.log.1", [_line(f"r{i}") for i in range(3)])
    log = _write(tmp_path / "server.log", [_line(f"e{i}") for i in range(10)])
    newest = read_page(log, limit=4)
    assert [r["event"] for r in newest["records"]] == ["e6", "e7", "e8", "e9"]
    older = read_page(log, before=parse_cursor(newest["before"]), limit=100)
    assert [r["event"] for r in older["records"]] == [f"e{i}" for i in range(6)]
    rotated = read_page(log, before=parse_cursor(older["before"]))
    assert [r["event"] for r in rotated["records"]] == ["r0", "r1", "r2"] and rotated["before"] is None


def test_cursor_is_validated() -> None:
    assert parse_cursor(None) is None
    with pytest.raises(ValueError):
        parse_cursor("../etc")


def _app(log: Path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(server_log_routes, "server_log_path", lambda: log)
    app = FastAPI()
    app.include_router(server_log_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


def test_route_v2_and_v1_side_by_side(tmp_path: Path, monkeypatch) -> None:
    log = _write(tmp_path / "server.log", [_line("one"), "[STDERR] Traceback (most recent call last):", _line("two", "error")])
    with TestClient(_app(log, monkeypatch)) as http:
        v1 = http.get("/api/v1/server-log").json()
        assert [e["event"] for e in v1["entries"]] == ["one", "two"] and "records" not in v1
        v2 = http.get("/api/v1/server-log?v=2").json()
        assert v2["version"] == 2 and [r["level"] for r in v2["records"]] == ["info", "error", "error"]
        assert http.get(f"/api/v1/server-log?v=2&since={v2['head']}").json()["records"] == []
        assert http.get("/api/v1/server-log?v=2&since=nope").status_code == 422
        assert http.get(f"/api/v1/server-log?v=2&since={v2['head']}&before={v2['head']}").status_code == 422
        assert http.get("/api/v1/server-log?v=3").status_code == 422


def test_read_window_is_bounded(tmp_path: Path, monkeypatch) -> None:
    log = _write(tmp_path / "server.log", [_line(f"e{i}", pad="x" * 40) for i in range(5000)])
    seen: list[int] = []
    real = records_module._read

    def spy(path, start, end):
        seen.append(end - start)
        return real(path, start, end)

    monkeypatch.setattr(records_module, "_read", spy)
    page = read_page(log, max_bytes=16 * 1024, limit=10**6)
    assert max(seen) <= 16 * 1024 and page["records"][-1]["event"] == "e4999"


ASGI_BLOCK = [
    "[STDERR] ERROR:    Exception in ASGI application",
    "Traceback (most recent call last):",
    '  File "/srv/venv/anyio/streams/memory.py", line 118, in receive',
    "    return self.receive_nowait()",
    "           ~~~~~~~~~~~~~~~~~~~^^",
    "anyio.WouldBlock",
    "",
    "During handling of the above exception, another exception occurred:",
    "",
    "Traceback (most recent call last):",
    '  File "/srv/venv/uvicorn/protocols/http/httptools_impl.py", line 422, in run_asgi',
    "    result = await app(",
    "    ...<5 lines>...",
    "asyncio.exceptions.CancelledError: Task cancelled, timeout graceful shutdown exceeded",
]


def _timed(event: str, stamp: str) -> str:
    return "[STDOUT] " + json.dumps({"event": event, "timestamp": stamp, "level": "info"})


def test_uvicorn_block_is_one_error_record_with_the_last_exception_line(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_timed("a", "2026-10-16T10:00:00Z"), *ASGI_BLOCK, _timed("b", "2026-10-16T10:00:05Z")])
    got = read_page(log)["records"]
    assert [r["event"] for r in got] == [
        "a",
        "asyncio.exceptions.CancelledError: Task cancelled, timeout graceful shutdown exceeded",
        "b",
    ]
    crash = got[1]
    assert (crash["level"], crash["source"], crash["traceback"], crash["continues"]) == ("error", "stderr", True, False)
    assert crash["lines"][0] == "ERROR:    Exception in ASGI application"
    assert crash["lines"].count("Traceback (most recent call last):") == 2
    assert "During handling of the above exception, another exception occurred:" in crash["lines"]
    assert "    ...<5 lines>..." in crash["lines"] and crash["lines"][-1].startswith("asyncio.exceptions.CancelledError")
    assert crash["lines"].index("") < crash["lines"].index("During handling of the above exception, another exception occurred:")


def test_untimed_record_takes_the_nearest_earlier_time_and_says_so(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [
        _timed("a", "2026-10-16T10:00:00Z"), _timed("b", "2026-10-16T10:00:05Z"), *ASGI_BLOCK, *ASGI_BLOCK, _timed("c", "2026-10-16T10:01:00Z"),
    ])
    got = read_page(log)["records"]
    assert [(r["timestamp"], r["approx_time"]) for r in got] == [
        ("2026-10-16T10:00:00Z", False),
        ("2026-10-16T10:00:05Z", False),
        ("2026-10-16T10:00:05Z", True),
        ("2026-10-16T10:00:05Z", True),
        ("2026-10-16T10:01:00Z", False),
    ]


def test_untimed_record_with_no_earlier_time_stays_blank_and_exact_flag_false(tmp_path: Path) -> None:
    got = read_page(_write(tmp_path / "server.log", ASGI_BLOCK))["records"]
    assert len(got) == 1 and got[0]["timestamp"] == "" and got[0]["approx_time"] is False


def test_a_plain_line_after_a_closed_block_is_its_own_record(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [_timed("a", "2026-10-16T10:00:00Z"), *ASGI_BLOCK, "INFO:     Shutting down"])
    got = read_page(log)["records"]
    assert [(r["event"], r["level"]) for r in got][-1] == ("INFO:     Shutting down", "info")
    assert len(got) == 3 and got[2]["approx_time"] is True


def test_bare_traceback_without_the_header_folds_too(tmp_path: Path) -> None:
    log = _write(tmp_path / "server.log", [
        _timed("a", "2026-10-16T10:00:00Z"), "Traceback (most recent call last):", '  File "x.py", line 1, in f', "KeyError: 'k'",
        "The above exception was the direct cause of the following exception:", "", "Traceback (most recent call last):",
        '  File "y.py", line 2, in g', "RuntimeError: wrapped",
    ])
    got = read_page(log)["records"]
    assert [r["event"] for r in got] == ["a", "RuntimeError: wrapped"]
    assert len(got[1]["lines"]) == 8


def test_structured_json_records_keep_their_own_time(tmp_path: Path) -> None:
    got = read_page(_write(tmp_path / "server.log", [_timed("a", "2026-10-16T10:00:00Z"), _line("b")]))["records"]
    assert [(r["timestamp"], r["approx_time"]) for r in got] == [("2026-10-16T10:00:00Z", False), ("2026-10-16T10:00:00Z", False)]
