
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated

CONV_ON_DISK = "11111111-2222-3333-4444-555555555555"
CONV_GONE = "99999999-8888-7777-6666-555555555555"


def _app(auth_ok: bool = True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if auth_ok:
        app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _session(conn, *, uuid, name, project_id, lifecycle="stopped", source="tmux_missing",
             archived_at=None, agent="claude", conv=None, work_at="2026-09-20T10:00:00Z", epoch=1000):
    conn.execute(
        "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, "
        "lifecycle, lifecycle_source, archived_at, project_id, agent_type, claude_session_uuid, "
        "title, last_work_at, created_at, updated_at) "
        "VALUES (?, 'created', 'cloude', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid, name, epoch, lifecycle, source, archived_at, project_id, agent, conv,
         name, work_at, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    )


@pytest.fixture()
def seeded(monkeypatch, tmp_path):
    from src.api import projects_history_routes
    from src.core.project_history import transcripts as transcripts_mod

    state = tmp_path / "state"
    state.mkdir()
    corpus = tmp_path / "corpus"
    (corpus / "-Users-x-alpha").mkdir(parents=True)
    (corpus / "-Users-x-alpha" / f"{CONV_ON_DISK}.jsonl").write_text("{}\n")
    monkeypatch.setattr(type(projects_history_routes.settings), "get_state_dir", lambda self: state)
    monkeypatch.setattr(transcripts_mod, "claude_transcript_roots", lambda: (corpus,))

    ensure_db_migrated(state, 4, "test")
    conn = connect(db_path_for(state), create=True)
    try:
        for pid, root, name, archived in ((1, "/x/alpha", "alpha", None), (2, "/x/beta", "beta", "2026-09-10T00:00:00Z")):
            conn.execute(
                "INSERT INTO projects (id, root, raw_path, display_name, source, archived_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'test', ?, '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                (pid, root, root, name, archived),
            )
        _session(conn, uuid="run", name="alpha-live", project_id=1, lifecycle="running", source="tmux_list",
                 work_at="2026-09-27T10:00:00Z", epoch=1)
        _session(conn, uuid="nap", name="alpha-nap", project_id=1, source="slept_by_user", conv=CONV_ON_DISK, epoch=2)
        _session(conn, uuid="done", name="alpha-done", project_id=1, conv=CONV_GONE, agent="codex",
                 work_at="2026-08-01T10:00:00Z", epoch=3)
        _session(conn, uuid="gone", name="beta-removed", project_id=2, archived_at="2026-09-11T00:00:00Z", epoch=4)
        _session(conn, uuid="loose", name="loose", project_id=None, lifecycle="unknown", source="probe_failed", epoch=5)
        conn.commit()
    finally:
        conn.close()
    return state


def test_refuses_without_auth(seeded):
    assert _app(auth_ok=False).get("/api/v1/projects/history").status_code in (401, 403)


def test_every_project_and_state_in_the_default_page(seeded):
    body = _app().get("/api/v1/projects/history").json()
    assert body["state"] == "ok"
    assert body["total"] == 3 and body["next_offset"] is None
    keys = [g["key"] for g in body["groups"]]
    assert keys[-1] == "none", "the no-project group always sorts last"
    by_uuid = {s["session_uuid"]: s for g in body["groups"] for s in g["sessions"]}
    assert {u: s["state"] for u, s in by_uuid.items()} == {
        "run": "running", "nap": "asleep", "done": "closed", "gone": "removed", "loose": "unknown",
    }
    beta = next(g for g in body["groups"] if g["key"] == "2")
    assert beta["project"]["archived_at"], "an archived project is listed with its stamp"
    assert body["facets"]["agents"] == ["claude", "codex"]


def test_has_transcript_reads_the_live_corpus(seeded):
    body = _app().get("/api/v1/projects/history").json()
    by_uuid = {s["session_uuid"]: s for g in body["groups"] for s in g["sessions"]}
    assert by_uuid["nap"]["has_transcript"] is True
    assert by_uuid["done"]["claude_session_uuid"] == CONV_GONE
    assert by_uuid["done"]["has_transcript"] is False
    assert by_uuid["run"]["has_transcript"] is False, "no conversation id is never resumable"


def test_state_filter_drops_empty_projects_when_asked(seeded):
    body = _app().get("/api/v1/projects/history?state=running,asleep&include_empty=false").json()
    assert [g["key"] for g in body["groups"]] == ["1"]
    assert {s["session_uuid"] for s in body["groups"][0]["sessions"]} == {"run", "nap"}
    assert body["facets"]["states"]["closed"] == 1, "chip counts ignore the state filter itself"


def test_search_matches_a_project_name_or_a_session(seeded):
    app = _app()
    by_project = app.get("/api/v1/projects/history?q=BETA").json()
    assert [g["key"] for g in by_project["groups"]] == ["2"]
    by_session = app.get("/api/v1/projects/history?q=alpha-done").json()
    assert [s["session_uuid"] for g in by_session["groups"] for s in g["sessions"]] == ["done"]


def test_agent_date_and_project_state_filters(seeded):
    app = _app()
    codex = app.get("/api/v1/projects/history?agent=codex&include_empty=false").json()
    assert [s["session_uuid"] for g in codex["groups"] for s in g["sessions"]] == ["done"]
    recent = app.get("/api/v1/projects/history?since=2026-09-15&include_empty=false").json()
    assert "done" not in {s["session_uuid"] for g in recent["groups"] for s in g["sessions"]}, (
        "a row last active in august is outside a since=2026-09-15 window"
    )
    window = app.get("/api/v1/projects/history?since=2026-07-01&until=2026-08-15&include_empty=false").json()
    assert [s["session_uuid"] for g in window["groups"] for s in g["sessions"]] == ["done"]
    archived = app.get("/api/v1/projects/history?project_state=archived").json()
    assert [g["key"] for g in archived["groups"]] == ["2"]


def test_pagination_by_group_and_session_limit(seeded):
    app = _app()
    first = app.get("/api/v1/projects/history?limit=2").json()
    assert len(first["groups"]) == 2 and first["next_offset"] == 2 and first["total"] == 3
    second = app.get("/api/v1/projects/history?limit=2&offset=2").json()
    assert len(second["groups"]) == 1 and second["next_offset"] is None
    capped = app.get("/api/v1/projects/history?project=1&session_limit=1").json()
    group = capped["groups"][0]
    assert group["session_total"] == 3 and len(group["sessions"]) == 1
    assert group["sessions"][0]["session_uuid"] == "run", "newest activity first"


@pytest.mark.parametrize(
    "query",
    ["state=bogus", "sort=sideways", "limit=0", "limit=101", "offset=-1", "since=notadate",
     "project=abc", "project_state=maybe", "since=2026-09-10&until=2026-09-01"],
)
def test_bad_parameters_are_400_naming_the_problem(seeded, query):
    resp = _app().get(f"/api/v1/projects/history?{query}")
    assert resp.status_code == 400
    assert resp.json()["detail"]


def test_no_datastore_is_a_named_state_not_an_empty_success(monkeypatch, tmp_path):
    from src.api import projects_history_routes

    monkeypatch.setattr(type(projects_history_routes.settings), "get_state_dir", lambda self: Path(tmp_path))
    body = _app().get("/api/v1/projects/history").json()
    assert body["state"] == "no_datastore" and body["groups"] == []


def test_a_moved_away_project_names_its_new_computer_by_label_not_install_id(seeded):
    conn = connect(db_path_for(seeded), create=False)
    try:
        conn.execute("UPDATE projects SET pack_state = 'moved_away', moved_to_install_id = 'iid-studio-0001' WHERE id = 1")
        conn.execute("INSERT INTO hosts (key, label, ssh_target, socket, enabled, created_at, updated_at, peer_install_id) "
            "VALUES ('peer-studio', 'studio', 'x', 'cloude', 1, 't', 't', 'iid-studio-0001')")
        conn.commit()
    finally:
        conn.close()
    body = _app().get("/api/v1/projects/history").json()
    alpha = next(g for g in body["groups"] if g["key"] == "1")
    assert alpha["project"]["pack_state"] == "moved_away" and alpha["project"]["moved_to_label"] == "studio"
