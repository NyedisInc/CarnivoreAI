
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sub_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sub_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.attention.registry_record import REG_OK  # noqa: E402
from src.core.subagents import files  # noqa: E402

from tests.helpers.subagent_fixture import CONV, build_corpus  # noqa: E402


class _Watcher:

    def __init__(self, started_at: Optional[datetime], uuid: str = CONV) -> None:
        record = SimpleNamespace(verdict=REG_OK, session_uuid=uuid,
                                 record_session_uuid=uuid, started_at=started_at)
        self._observation = SimpleNamespace(stale=False,
                                            evidence=SimpleNamespace(registry=record))
        self.asked = []

    def observation_for(self, session_id, now=None):
        self.asked.append(session_id)
        return self._observation


class _Manager:

    def __init__(self, rows: dict, uuid: Optional[str], watcher=None) -> None:
        self._rows = rows
        self._uuid = uuid
        self._attention_watcher = watcher

    async def get_session_info(self, session_id=None):
        return self._rows.get(session_id)

    def claude_uuid_for_tmux_name(self, tmux_name):
        return self._uuid


def _info(family, tmux_name, row_id="ses_1"):
    return SimpleNamespace(agent_family=family, tmux_session=tmux_name,
                           session=SimpleNamespace(id=row_id, working_dir=None))


@pytest.fixture(autouse=True)
def _fresh():
    files.reset_caches_for_tests()
    yield
    files.reset_caches_for_tests()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    target = tmp_path / "projects"
    build_corpus(target)
    import src.api.subagent_routes as routes_mod
    from src.core.subagents.session import read_session_subagents as real

    monkeypatch.setattr(routes_mod, "read_session_subagents",
                        lambda subject, **kw: real(subject, projects_dir=target, **kw))
    return target


def _client(manager, *, aggregator: bool = False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth

    if aggregator:
        from src.api.routes import router
    else:
        from src.api.subagent_routes import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    return TestClient(app)


def test_the_route_returns_the_list_and_the_counts(corpus):
    body = _client(_Manager({"ses_1": _info("claude", "cloude_a")}, CONV)).get(
        "/api/v1/sessions/ses_1/subagents").json()
    assert body["state"] == "ok" and body["conversation_uuid"] == CONV
    assert body["counts"]["total"] == 9 and body["counts"]["internal"] == 1
    assert body["contract_versions"] == {"subagent_meta": 1, "subagent_jsonl": 1}
    row = body["subagents"][0]
    for key in ("id", "agent_type", "description", "model", "background", "spawn_depth",
                "started_at", "last_activity_at", "status", "status_reason"):
        assert key in row
    assert "/" not in body["detail"]


def test_the_process_start_is_asked_for_by_row_id_and_used(corpus, monkeypatch):
    started = datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)
    watcher = _Watcher(started_at=started)
    seen = {}
    import src.api.subagent_routes as routes_mod

    wrapped = routes_mod.read_session_subagents

    def spy(subject, **kw):
        seen.update(kw)
        return wrapped(subject, **kw)

    monkeypatch.setattr(routes_mod, "read_session_subagents", spy)
    manager = _Manager({"adopted:cloude_x": _info("claude", "cloude_x", "ses_row")},
                       CONV, watcher)
    assert _client(manager).get("/api/v1/sessions/adopted:cloude_x/subagents").status_code == 200
    assert watcher.asked == ["ses_row"]
    assert seen["process_started_at"] == started


def test_a_registry_record_for_another_conversation_is_not_used():
    from src.api.subagent_routes import process_started_at_for

    started = datetime(2026, 9, 26, 11, 0, tzinfo=timezone.utc)
    same = _Manager({}, CONV, _Watcher(started_at=started))
    other = _Manager({}, CONV, _Watcher(started_at=started, uuid="another-conversation"))
    assert process_started_at_for(same, "ses_1", CONV) == started
    assert process_started_at_for(other, "ses_1", CONV) is None
    assert process_started_at_for(_Manager({}, CONV, None), "ses_1", CONV) is None


def test_codex_answers_not_applicable_with_no_counts():
    body = _client(_Manager({"ses_1": _info("codex", "cloude_c")}, "t")).get(
        "/api/v1/sessions/ses_1/subagents").json()
    assert body["state"] == "not_applicable" and body["counts"] is None


def test_an_unknown_session_is_a_404():
    assert _client(_Manager({}, None)).get("/api/v1/sessions/nope/subagents").status_code == 404


def test_the_route_is_served_through_the_aggregator(corpus):
    client = _client(_Manager({"ses_1": _info("claude", "cloude_a")}, CONV), aggregator=True)
    assert client.get("/api/v1/sessions/ses_1/subagents").status_code == 200
    missing = client.get("/api/v1/sessions/ses_1/not-a-route")
    assert missing.status_code == 404 and missing.json()["detail"] == "Not Found"
