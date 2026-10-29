
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sublist_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sublist_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.subagent_listing import mark_subagents, tally_for
from src.core.attention.registry_record import REG_OK
from src.core.subagents import files, tally as tally_mod
from src.core.subagents.tally import (
    NOT_APPLICABLE,
    REFRESH_SECONDS,
    SubagentTally,
    SubagentTallyCache,
    process_start_for,
)
from src.models import Session, SessionInfo
from tests.helpers.subagent_fixture import B, CONV, _parent, build_corpus, notification, ts

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class _Clock:

    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    yield
    files.reset_caches_for_tests()


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "projects"
    parent = build_corpus(root)
    return root, parent




def test_a_claude_conversation_is_counted_from_the_real_corpus(corpus):
    root, _ = corpus
    got = SubagentTallyCache(projects_dir=root).tally("claude", CONV, None, None, NOW)
    assert got.state == "ok"
    assert got.total == 9, "every user agent file, the internal one excluded"
    assert got.running is not None and got.running >= 1
    assert got.unknown is not None and got.unknown >= 1
    assert got.running + got.unknown <= got.total


def test_a_null_family_is_read_as_claude_like_the_route(corpus):
    root, _ = corpus
    assert SubagentTallyCache(projects_dir=root).tally(None, CONV, None, None, NOW).state == "ok"


@pytest.mark.parametrize("family", ["codex", "shell"])
def test_a_family_with_no_subagent_files_is_not_applicable_never_zero(corpus, family):
    root, _ = corpus
    got = SubagentTallyCache(projects_dir=root).tally(family, CONV, None, None, NOW)
    assert got.state == "not_applicable"
    assert got.running is None and got.total is None and got.unknown is None


def test_no_conversation_yet_is_a_measured_zero():
    got = SubagentTallyCache().tally("claude", None, None, None, NOW)
    assert (got.state, got.running, got.total) == ("absent", 0, 0)


def test_a_conversation_with_no_transcript_is_absent_with_zeros(corpus):
    root, _ = corpus
    got = SubagentTallyCache(projects_dir=root).tally(
        "claude", "00000000-0000-4000-8000-000000000000", None, None, NOW)
    assert (got.state, got.running, got.total) == ("absent", 0, 0)


def test_an_unchanged_conversation_is_not_reclassified(corpus, monkeypatch):
    root, parent = corpus
    calls = []
    real = tally_mod.read_subagents
    monkeypatch.setattr(tally_mod, "read_subagents",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    clock = _Clock()
    cache = SubagentTallyCache(projects_dir=root, clock=clock)
    first = cache.tally("claude", CONV, None, None, NOW)
    clock.at += 2
    assert cache.tally("claude", CONV, None, None, NOW) == first
    assert len(calls) == 1
    with parent.open("a") as handle:
        handle.write("\n")
    clock.at += 2
    cache.tally("claude", CONV, None, None, NOW)
    assert len(calls) == 1
    with parent.open("a") as handle:
        handle.write(json.dumps(_parent("user", ts(11, 59), promptId="p",
                                        origin={"kind": "task-notification"},
                                        message={"role": "user",
                                                 "content": notification([B], "completed")})) + "\n")
    clock.at += 2
    cache.tally("claude", CONV, None, None, NOW)
    assert len(calls) == 2
    cache.tally("claude", CONV, None, NOW, NOW)
    assert len(calls) == 3
    clock.at += REFRESH_SECONDS + 1
    cache.tally("claude", CONV, None, NOW, NOW)
    assert len(calls) == 4


def test_the_cache_is_bounded(corpus, monkeypatch):
    root, _ = corpus
    monkeypatch.setattr(tally_mod, "MAX_ENTRIES", 3)
    cache = SubagentTallyCache(projects_dir=root)
    for n in range(10):
        cache.tally("claude", f"00000000-0000-4000-8000-{n:012d}", None, None, NOW)
    assert len(cache._entries) == 3


def test_the_process_start_is_used_only_for_a_positive_record_of_this_conversation():
    start = datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)
    ok = SimpleNamespace(verdict=REG_OK, session_uuid=CONV, record_session_uuid=None,
                         started_at=start)
    assert process_start_for(ok, CONV) == start
    assert process_start_for(ok, "other") is None
    assert process_start_for(SimpleNamespace(verdict="absent", session_uuid=CONV,
                                             record_session_uuid=CONV, started_at=start),
                             CONV) is None
    assert process_start_for(None, CONV) is None




class _Watcher:

    def __init__(self, tallies: dict, stale: bool = False) -> None:
        self._tallies = tallies
        self._stale = stale
        self.asked = []

    def observation_for(self, session_id, now=None):
        self.asked.append(session_id)
        if session_id not in self._tallies:
            return None
        return SimpleNamespace(stale=self._stale,
                               evidence=SimpleNamespace(subagents=self._tallies[session_id], transcript=SimpleNamespace(verdict="unreadable")))


def _info(session_id: str, family: Optional[str] = "claude") -> SessionInfo:
    return SessionInfo(session=Session(id=session_id, working_dir="/tmp"),
                       agent_family=family)


def test_an_observed_tally_lands_on_the_wrapper_not_the_session():
    infos = [_info("ses_a")]
    watcher = _Watcher({"ses_a": SubagentTally("ok", running=2, total=5, unknown=1)})
    mark_subagents(SimpleNamespace(_attention_watcher=watcher), infos)
    assert infos, "the stamp must have rows to look at"
    body = infos[0].model_dump()
    assert (body["subagents_state"], body["subagents_running"], body["subagents_total"]) == (
        "ok", 2, 5)
    assert "subagents_running" not in body["session"], "gotcha 1: wrapper only"
    assert watcher.asked == ["ses_a"], "keyed on the row id the watcher files under"


def test_a_measured_zero_is_zero():
    infos = [_info("ses_a")]
    mark_subagents(SimpleNamespace(_attention_watcher=_Watcher(
        {"ses_a": SubagentTally("ok", running=0, total=0, unknown=0)})), infos)
    assert (infos[0].subagents_running, infos[0].subagents_total) == (0, 0)


def test_codex_is_not_applicable_with_null_counts_even_unobserved():
    infos = [_info("ses_c", family="codex")]
    mark_subagents(SimpleNamespace(_attention_watcher=_Watcher({})), infos)
    assert infos[0].subagents_state == "not_applicable"
    assert infos[0].subagents_running is None and infos[0].subagents_total is None


@pytest.mark.parametrize("watcher", [None, _Watcher({}), _Watcher(
    {"ses_a": SubagentTally("ok", running=3, total=3, unknown=0)}, stale=True)])
def test_no_fresh_observation_is_null_never_zero(watcher):
    info = _info("ses_a")
    info.subagents_state, info.subagents_running, info.subagents_total = "ok", 3, 3
    mark_subagents(SimpleNamespace(_attention_watcher=watcher), [info])
    assert (info.subagents_state, info.subagents_running, info.subagents_total) == (
        None, None, None)


def test_tally_for_prefers_the_family_over_a_missing_observation():
    assert tally_for(None, _info("x", "codex"), NOW) is NOT_APPLICABLE
    assert tally_for(None, _info("x", "claude"), NOW) is None


def test_the_listing_route_serves_the_fields(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.session_crud_routes import router

    class _Manager:
        _attention_watcher = _Watcher({
            "ses_a": SubagentTally("ok", running=1, total=4, unknown=0),
        })

        async def list_session_infos(self):
            return [_info("ses_a"), _info("ses_b"), _info("ses_c", family="codex")]

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager()
    rows = TestClient(app).get("/api/v1/sessions/list").json()
    by_id = {row["session"]["id"]: row for row in rows}
    assert set(by_id) == {"ses_a", "ses_b", "ses_c"}
    assert (by_id["ses_a"]["subagents_running"], by_id["ses_a"]["subagents_total"]) == (1, 4)
    assert by_id["ses_b"]["subagents_state"] is None and by_id["ses_b"]["subagents_running"] is None
    assert by_id["ses_c"]["subagents_state"] == "not_applicable"
    assert by_id["ses_c"]["subagents_running"] is None
