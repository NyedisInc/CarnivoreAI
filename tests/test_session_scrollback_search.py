
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_xs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_xs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import cross_session_search as xs
from src.core.product_identity import TMUX_SESSION_PREFIX




def test_query_is_trimmed_and_bounded():
    assert xs.normalize_query("  error ") == "error"
    with pytest.raises(xs.QueryRejected) as short:
        xs.normalize_query(" a ")
    assert short.value.code == "too_short"
    with pytest.raises(xs.QueryRejected) as long_:
        xs.normalize_query("x" * (xs.MAX_QUERY_CHARS + 1))
    assert long_.value.code == "too_long"
    with pytest.raises(xs.QueryRejected):
        xs.normalize_query(None)


def test_escapes_and_controls_are_stripped():
    raw = "\x1b[31mred\x1b[0m \x1b]0;title\x07plain\x1b(B\rend\x00"
    assert xs.strip_ansi(raw) == "red plainend"
    assert xs.strip_ansi("tab\tkept\nnewline") == "tab\tkept\nnewline"


def test_matching_is_literal_and_case_insensitive():
    text = "a.c here\nabc here\nA.C again a.c"
    total, found = xs.find_matches(text, "A.C", 10)
    assert total == 3
    assert [m["line"] for m in found] == [2, 2, 0]
    assert [m["occurrence_from_end"] for m in found] == [0, 1, 2]
    assert found[0]["match"] == "a.c"
    assert found[1]["match"] == "A.C"


def test_regex_metacharacters_cannot_inject():
    total, _ = xs.find_matches("(((( [a-z]+ .*", "[a-z]+", 5)
    assert total == 1
    total, _ = xs.find_matches("nothing", ".*", 5)
    assert total == 0


def test_snippet_trims_long_context():
    line = "x" * 500 + "NEEDLE" + "y" * 500
    _, found = xs.find_matches(line, "needle", 1)
    hit = found[0]
    assert hit["match"] == "NEEDLE"
    assert hit["before"].startswith("...") and len(hit["before"]) <= xs.CONTEXT_BEFORE + 3
    assert hit["after"].endswith("...") and len(hit["after"]) <= xs.CONTEXT_AFTER + 3


def test_keep_caps_matches_but_not_the_count():
    total, found = xs.find_matches("hit\n" * 50, "hit", 5)
    assert total == 50
    assert len(found) == 5
    assert found[0]["line"] == 49




def _targets(n: int):
    return [xs.SearchTarget(f"ses_{i}", f"{TMUX_SESSION_PREFIX}{i}", "sock") for i in range(n)]


def test_per_session_and_total_caps(monkeypatch):
    monkeypatch.setattr(xs, "capture_text", lambda t, lines: ("word\n" * 100, False))
    monkeypatch.setattr(xs, "MAX_TOTAL_MATCHES", 30)
    out = asyncio.run(xs.search_targets(_targets(3), "word"))
    kept = [len(s["matches"]) for s in out["sessions"]]
    assert kept == [20, 10, 0]
    assert out["total_matches"] == 300
    assert out["truncated"] is True
    assert all(s["match_count"] == 100 for s in out["sessions"])


def test_sessions_without_a_hit_are_left_out(monkeypatch):
    texts = {"ses_0": "nothing", "ses_1": "a word"}
    monkeypatch.setattr(xs, "capture_text", lambda t, lines: (texts[t.session_id], False))
    out = asyncio.run(xs.search_targets(_targets(2), "word"))
    assert [s["session_id"] for s in out["sessions"]] == ["ses_1"]
    assert out["searched"] == 2


def test_depth_is_clamped(monkeypatch):
    seen = []
    monkeypatch.setattr(xs, "capture_text", lambda t, lines: (seen.append(lines) or "", False))
    asyncio.run(xs.search_targets(_targets(1), "word", lines=10**9))
    assert seen == [xs.MAX_LINES_PER_SESSION]


def test_unreadable_and_timed_out_panes_are_named_not_fatal(monkeypatch):
    def capture(target, lines):
        if target.session_id == "ses_0":
            raise RuntimeError("capture failed")
        if target.session_id == "ses_1":
            raise subprocess.TimeoutExpired(["tmux"], 3)
        return "word", False

    monkeypatch.setattr(xs, "capture_text", capture)
    out = asyncio.run(xs.search_targets(_targets(3), "word"))
    errors = {s["session_id"]: s["error"] for s in out["sessions"]}
    assert errors == {"ses_0": "unreadable", "ses_1": "timeout", "ses_2": None}
    assert out["timed_out"] == 1


def test_deadline_reports_slow_sessions_as_timed_out(monkeypatch):
    def capture(target, lines):
        if target.session_id == "ses_0":
            time.sleep(0.5)
        return "word", False

    monkeypatch.setattr(xs, "capture_text", capture)
    started = time.monotonic()
    out = asyncio.run(xs.search_targets(_targets(2), "word", deadline_s=0.1))
    assert time.monotonic() - started < 2
    errors = {s["session_id"]: s["error"] for s in out["sessions"]}
    assert errors == {"ses_0": "timeout", "ses_1": None}


def test_concurrency_is_bounded_across_requests(monkeypatch):
    import threading

    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def capture(target, lines):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return "word", False

    monkeypatch.setattr(xs, "capture_text", capture)

    async def two_searches():
        return await asyncio.gather(
            xs.search_targets(_targets(6), "word"), xs.search_targets(_targets(6), "word")
        )

    first, second = asyncio.run(two_searches())
    assert first["searched"] == second["searched"] == 6
    assert state["peak"] <= xs.MAX_CONCURRENCY


def test_targets_are_scoped_to_the_socket_and_the_prefix():
    backends = {
        "ses_ok": SimpleNamespace(tmux_session=f"{TMUX_SESSION_PREFIX}a", socket_name="mine"),
        "adopted:cloude_b": SimpleNamespace(tmux_session="cloude_b", socket_name="mine"),
        "ses_foreign": SimpleNamespace(tmux_session="personal", socket_name="mine"),
        "ses_other_socket": SimpleNamespace(tmux_session=f"{TMUX_SESSION_PREFIX}c", socket_name="theirs"),
        "ses_pty": SimpleNamespace(),
        "ses_bad": SimpleNamespace(tmux_session=f"{TMUX_SESSION_PREFIX}d:0", socket_name="mine"),
    }
    manager = SimpleNamespace(_registry=SimpleNamespace(backends=backends))
    got = [t.session_id for t in xs.collect_targets(manager, "mine")]
    assert got == ["ses_ok", "adopted:cloude_b"]




class _Manager:
    def __init__(self, backends):
        self._registry = SimpleNamespace(backends=backends)

    def tmux_socket_name(self):
        return "mine"


def _app(authed: bool, backends=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager(backends or {})
    return TestClient(app)


def test_route_requires_auth():
    response = _app(False).get("/api/v1/sessions/scrollback-search?q=word")
    assert response.status_code in (401, 403)


def test_route_rejects_bad_queries():
    client = _app(True)
    short = client.get("/api/v1/sessions/scrollback-search?q=a")
    assert short.status_code == 422
    assert short.json()["detail"]["code"] == "too_short"
    long_ = client.get("/api/v1/sessions/scrollback-search", params={"q": "x" * 201})
    assert long_.json()["detail"]["code"] == "too_long"


def test_route_answers_through_the_aggregator(monkeypatch):
    monkeypatch.setattr(xs, "capture_text", lambda t, lines: ("\x1b[1mfound word\x1b[0m", False))
    backends = {"ses_1": SimpleNamespace(tmux_session=f"{TMUX_SESSION_PREFIX}a", socket_name="mine")}
    response = _app(True, backends).get("/api/v1/sessions/scrollback-search?q=WORD")
    assert response.status_code == 200
    body = response.json()
    assert body["searched"] == 1
    hit = body["sessions"][0]["matches"][0]
    assert (hit["before"], hit["match"], hit["after"]) == ("found ", "word", "")
    assert _app(True).get("/api/v1/sessions/scrollback-searchx?q=word").status_code == 404




@pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")
def test_real_tmux_scope_ansi_and_occurrence():
    from tests.socket_guard import derive_test_socket

    mine = derive_test_socket("xsearch")
    other = derive_test_socket("xsearch_other")
    tmux = shutil.which("tmux")

    def run(sock, *args):
        return subprocess.run([tmux, "-L", sock, "-f", "/dev/null", *args],
                              capture_output=True, check=False, timeout=10)

    ours = f"{TMUX_SESSION_PREFIX}xs_a"
    alt = f"{TMUX_SESSION_PREFIX}xs_alt"
    script = ("seq 1 300; printf '\\033[31mzebra\\033[0m one\\n'; seq 1 5; "
              "printf 'ZEBRA two\\n'; sleep 30")
    alt_script = "printf '\\033[?1049hzebra on alt\\n'; sleep 30"
    try:
        for sock, name, cmd in (
            (mine, ours, script),
            (mine, "personal", "printf 'zebra personal\\n'; sleep 30"),
            (mine, alt, alt_script),
            (other, f"{TMUX_SESSION_PREFIX}xs_b", "printf 'zebra other\\n'; sleep 30"),
        ):
            result = run(sock, "new-session", "-d", "-s", name, "-x", "100", "-y", "20", cmd)
            assert result.returncode == 0, result.stderr
        run(mine, "set-option", "-g", "history-limit", "5000")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if b"ZEBRA two" in run(mine, "capture-pane", "-p", "-S", "-", "-t", ours).stdout:
                break
            time.sleep(0.1)

        backends = {
            "ses_a": SimpleNamespace(tmux_session=ours, socket_name=mine),
            "ses_alt": SimpleNamespace(tmux_session=alt, socket_name=mine),
            "ses_personal": SimpleNamespace(tmux_session="personal", socket_name=mine),
            "ses_b": SimpleNamespace(tmux_session=f"{TMUX_SESSION_PREFIX}xs_b", socket_name=other),
        }
        manager = SimpleNamespace(_registry=SimpleNamespace(backends=backends))
        targets = xs.collect_targets(manager, mine)
        assert [t.session_id for t in targets] == ["ses_a", "ses_alt"]

        out = asyncio.run(xs.search_targets(targets, "zebra"))
        by_id = {s["session_id"]: s for s in out["sessions"]}
        assert set(by_id) == {"ses_a", "ses_alt"}

        found = by_id["ses_a"]
        assert found["match_count"] == 2
        newest, older = found["matches"]
        assert (newest["occurrence_from_end"], newest["match"]) == (0, "ZEBRA")
        assert (older["occurrence_from_end"], older["match"]) == (1, "zebra")
        assert older["after"] == " one"
        assert found["alternate_screen"] is False

        assert by_id["ses_alt"]["alternate_screen"] is True
        assert by_id["ses_alt"]["match_count"] == 1

        gone = xs.SearchTarget("ses_gone", f"{TMUX_SESSION_PREFIX}xs_al", mine)
        out = asyncio.run(xs.search_targets([gone], "zebra"))
        assert out["total_matches"] == 0
        assert out["sessions"][0]["error"] == "unreadable"
    finally:
        run(mine, "kill-server")
        run(other, "kill-server")
