
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tmr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tmr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.attention.registry_read import REG_ABSENT, REG_OK, REG_UNREADABLE  # noqa: E402
from src.core.attention.transcript_facts import FACTS_FOUND  # noqa: E402
from src.core.timers import index as index_mod  # noqa: E402
from src.core.timers.tally import TimerTallyCache  # noqa: E402
from tests.helpers.timer_fixture import CONV, WORKDIR, Transcript, at  # noqa: E402


def _record(verdict=REG_OK, started: Optional[datetime] = at(8, 0), uuid=CONV):
    return SimpleNamespace(verdict=verdict, session_uuid=uuid,
                           record_session_uuid=uuid, started_at=started)


class _Watcher:

    def __init__(self, record, open_background: int = 2, timers=None) -> None:
        facts = SimpleNamespace(verdict=FACTS_FOUND, open_background_tasks=open_background)
        self.observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(
            registry=record, transcript=facts, identity=(None, None, None, None, CONV),
            timers=timers, subagents=None))
        self.asked = []

    def observation_for(self, session_id, now=None):
        self.asked.append(session_id)
        return self.observation


class _Manager:
    def __init__(self, rows: dict, watcher=None) -> None:
        self._rows = rows
        self._attention_watcher = watcher

    async def get_session_info(self, session_id=None):
        return self._rows.get(session_id)

    def _claude_uuid_for_tmux_name(self, tmux_name):
        return CONV


def _info(family="claude", row_id="ses_1"):
    return SimpleNamespace(agent_family=family, tmux_session="cloude_a",
                           session=SimpleNamespace(id=row_id, working_dir=WORKDIR))


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    t = Transcript()
    t.prompt(at(9, 0))
    t.wakeup(at(10, 0), "toolu_w1", delay=1800)
    t.cron(at(10, 0), "toolu_c1", "49759e95", "*/5 * * * *")
    t.cron(at(10, 1), "toolu_c2", "ef56ab78", "*/30 * * * *")
    t.cron_delete(at(10, 2), "toolu_d1", "ef56ab78")
    t.write(projects)
    monkeypatch.setattr(index_mod, "TIMER_INDEX_CACHE", index_mod.IncrementalCache())
    import src.api.session_timers_routes as routes_mod
    from src.core.timers.session import read_session_timers as real

    monkeypatch.setattr(routes_mod, "read_session_timers",
                        lambda subject, process, **kw: real(
                            subject, process, projects_dir=projects, now=at(10, 5), **kw))
    return projects


def _client(manager, *, authenticated: bool = True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authenticated:
        app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    return TestClient(app)


def test_the_route_lists_live_and_cancelled_timers(corpus):
    watcher = _Watcher(_record())
    body = _client(_Manager({"ses_1": _info()}, watcher)).get(
        "/api/v1/sessions/ses_1/timers").json()
    assert body["state"] == "ok" and body["process"] == "alive"
    assert body["counts"]["live"] == 2 and body["counts"]["cancelled"] == 1
    assert body["next_fire_at"] == "2026-09-27T10:10:00Z"
    statuses = {row["id"]: row["status"] for row in body["timers"]}
    assert statuses == {"toolu_w1": "live", "49759e95": "live", "ef56ab78": "cancelled"}
    assert body["background"]["open"] == 2 and "floor" in body["background"]["detail"]
    assert body["contract_versions"] == {"timer_call": 1, "timer_result": 1}
    assert watcher.asked == ["ses_1"]


def test_a_dead_process_has_no_live_timers(corpus):
    body = _client(_Manager({"ses_1": _info()}, _Watcher(_record(verdict=REG_ABSENT)))).get(
        "/api/v1/sessions/ses_1/timers").json()
    assert body["state"] == "ok" and body["process"] == "gone"
    assert body["counts"]["live"] == 0 and body["counts"]["lost"] == 2
    assert body["next_fire_at"] is None


def test_a_process_started_after_the_timers_lost_them(corpus):
    body = _client(_Manager({"ses_1": _info()}, _Watcher(_record(started=at(10, 3))))).get(
        "/api/v1/sessions/ses_1/timers").json()
    assert body["counts"]["live"] == 0 and body["counts"]["lost"] == 2


def test_no_observation_is_unchecked_not_zero(corpus):
    body = _client(_Manager({"ses_1": _info()}, None)).get(
        "/api/v1/sessions/ses_1/timers").json()
    assert body["state"] == "unchecked" and body["counts"] is None
    assert body["background"]["open"] is None


def test_codex_is_not_applicable_never_zero(corpus):
    body = _client(_Manager({"ses_1": _info("codex")}, _Watcher(_record()))).get(
        "/api/v1/sessions/ses_1/timers").json()
    assert body["state"] == "not_applicable"
    assert body["counts"] is None and body["background"] is None


def test_an_unknown_session_is_a_404(corpus):
    assert _client(_Manager({}, None)).get("/api/v1/sessions/nope/timers").status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/sessions/ses_1/timers", "/api/v1/scheduled-tasks"])
def test_no_credentials_is_a_401(path):
    response = _client(SimpleNamespace(), authenticated=False).get(path)
    assert response.status_code == 401


def test_the_tally_follows_the_process(corpus):
    cache = TimerTallyCache(projects_dir=corpus)
    alive = cache.tally("claude", CONV, WORKDIR, _record(), at(10, 5))
    assert alive.state == "ok" and alive.live == 2 and alive.next_fire_at == at(10, 10)
    gone = cache.tally("claude", CONV, WORKDIR, _record(verdict=REG_ABSENT), at(10, 5))
    assert gone.state == "ok" and gone.live == 0 and gone.next_fire_at is None
    unknown = cache.tally("claude", CONV, WORKDIR, _record(verdict=REG_UNREADABLE), at(10, 5))
    assert unknown.state == "unchecked" and unknown.live is None
    assert cache.tally("codex", CONV, WORKDIR, _record(), at(10, 5)).live is None
    assert cache.tally("claude", None, WORKDIR, _record(), at(10, 5)).live == 0


def test_the_tally_rereads_only_when_the_file_moved(corpus, monkeypatch):
    cache = TimerTallyCache(projects_dir=corpus)
    import src.core.timers.tally as tally_mod

    reads = []
    real = tally_mod.read_timer_index
    monkeypatch.setattr(tally_mod, "read_timer_index", lambda path: reads.append(path) or real(path))
    cache.tally("claude", CONV, WORKDIR, _record(), at(10, 5))
    cache.tally("claude", CONV, WORKDIR, _record(), at(10, 6))
    assert len(reads) == 1
    path = next(corpus.rglob("*.jsonl"))
    t = Transcript()
    t.prompt(at(10, 40), meta=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(t.text())
    after = cache.tally("claude", CONV, WORKDIR, _record(), at(10, 41))
    assert len(reads) == 2
    assert after.live == 1


def test_the_listing_stamp_is_on_the_wrapper_and_null_when_unmeasured():
    from src.api.timer_listing import mark_timers
    from src.core.timers.tally import TimerTally
    from src.models import SessionInfo

    def info(family, row_id):
        return SessionInfo.model_construct(
            agent_family=family, session=SimpleNamespace(id=row_id),
            timers_state="stale", timers_live=9, timers_next_fire_at="x")

    rows = [info("claude", "a"), info("codex", "b"), info("claude", "c")]
    tally = TimerTally("ok", live=1, next_fire_at=datetime(2026, 9, 27, 10, 10, tzinfo=timezone.utc))

    class W:
        def observation_for(self, session_id, now=None):
            if session_id != "a":
                return None
            return SimpleNamespace(stale=False, evidence=SimpleNamespace(timers=tally))

    mark_timers(SimpleNamespace(_attention_watcher=W()), rows)
    assert (rows[0].timers_state, rows[0].timers_live, rows[0].timers_next_fire_at) == (
        "ok", 1, "2026-09-27T10:10:00Z")
    assert (rows[1].timers_state, rows[1].timers_live) == ("not_applicable", None)
    assert (rows[2].timers_state, rows[2].timers_live, rows[2].timers_next_fire_at) == (
        None, None, None)
