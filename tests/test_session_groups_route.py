
from __future__ import annotations

import os
import tempfile
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_groups_routes import router as groups_router
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_GROUP_MAX, SESSION_GROUP_NAME_MAX


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    assert ensure_db_migrated(state_dir).status == "ok"

    app = FastAPI()
    app.include_router(groups_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        yield client, state_dir


def _names(body):
    return [g["name"] for g in body["groups"]]


def _store(state_dir, *names):
    out = []
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        with conn:
            for name in names:
                session_uuid = f"uuid-{name}"
                conn.execute(
                    "INSERT INTO sessions "
                    "(session_uuid, tmux_socket, tmux_name, origin, lifecycle, "
                    " created_at, updated_at) "
                    "VALUES (?, 'cloude', ?, 'created', 'running', "
                    "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                    (session_uuid, name),
                )
                out.append(session_uuid)
    return out




def test_no_groups_yet_is_ok_with_an_empty_list(app_env):
    client, _ = app_env
    body = client.get("/api/v1/session-groups").json()
    assert body["status"] == "ok"
    assert body["groups"] == []
    assert body["detail"] is None


def test_a_missing_datastore_is_unavailable_not_empty(app_env):
    client, state_dir = app_env
    db_path_for(state_dir).unlink()

    body = client.get("/api/v1/session-groups").json()

    assert body["status"] == "unavailable", (
        "an unreadable datastore reported as 'ok' - the client will draw "
        "this as 'you have no groups'"
    )
    assert body["groups"] == []
    assert body["detail"], "an unavailable read must say why"


def test_a_datastore_predating_v8_is_unavailable(app_env):
    client, state_dir = app_env
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            conn.execute("DROP TABLE session_group_members")
            conn.execute("DROP TABLE session_groups")

    body = client.get("/api/v1/session-groups").json()

    assert body["status"] == "unavailable"
    assert body["groups"] == []




def test_create_returns_the_whole_list(app_env):
    client, _ = app_env
    body = client.post("/api/v1/session-groups", json={"name": "work"}).json()
    assert body["status"] == "ok"
    assert _names(body) == ["work"]
    assert body["groups"][0]["members"] == []
    assert body["groups"][0]["group_uuid"]


def test_create_trims_and_bounds_the_name(app_env):
    client, _ = app_env
    body = client.post("/api/v1/session-groups", json={"name": "  a   b "}).json()
    assert _names(body) == ["a b"]

    blank = client.post("/api/v1/session-groups", json={"name": "   "})
    assert blank.status_code == 400

    long = client.post(
        "/api/v1/session-groups", json={"name": "x" * (SESSION_GROUP_NAME_MAX + 1)}
    )
    assert long.status_code == 400


def test_the_group_limit_is_a_409(app_env):
    client, _ = app_env
    for i in range(SESSION_GROUP_MAX):
        assert client.post("/api/v1/session-groups", json={"name": f"g{i}"}).status_code == 200
    over = client.post("/api/v1/session-groups", json={"name": "too many"})
    assert over.status_code == 409


def test_assign_moves_a_session_and_never_duplicates_it(app_env):
    client, state_dir = app_env
    _store(state_dir, "cloude_x")
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    b = client.post("/api/v1/session-groups", json={"name": "b"}).json()["groups"][1]

    client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": a["group_uuid"]},
    )
    body = client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": b["group_uuid"]},
    ).json()

    by_name = {g["name"]: g["members"] for g in body["groups"]}
    assert by_name["a"] == []
    assert by_name["b"] == ["cloude_x"]


def test_assign_null_returns_a_session_to_ungrouped(app_env):
    client, state_dir = app_env
    _store(state_dir, "cloude_x")
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": a["group_uuid"]},
    )

    body = client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": None},
    ).json()

    assert body["groups"][0]["members"] == []


def test_assign_to_a_missing_group_is_a_404(app_env):
    client, state_dir = app_env
    _store(state_dir, "cloude_x")
    r = client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": "nope"},
    )
    assert r.status_code == 404


def test_assigning_a_name_with_no_stored_session_is_a_409(app_env):
    client, _ = app_env
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    r = client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_never_seen", "group_uuid": a["group_uuid"]},
    )
    assert r.status_code == 409
    assert "cloude_never_seen" in r.json()["detail"]


def test_member_order_round_trips_over_http(app_env):
    client, state_dir = app_env
    keys = _store(state_dir, "cloude_1", "cloude_2", "cloude_3")
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    for name in ("cloude_1", "cloude_2", "cloude_3"):
        client.post(
            "/api/v1/session-groups/assign",
            json={"tmux_name": name, "group_uuid": a["group_uuid"]},
        )
    body = client.post(
        f"/api/v1/session-groups/{a['group_uuid']}/order",
        json={"session_uuids": [keys[2], keys[0], keys[1]]},
    ).json()
    assert body["groups"][0]["members"] == ["cloude_3", "cloude_1", "cloude_2"]
    assert body["groups"][0]["member_session_uuids"] == [keys[2], keys[0], keys[1]]


def test_rename_keeps_membership(app_env):
    client, state_dir = app_env
    _store(state_dir, "cloude_x")
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    client.post(
        "/api/v1/session-groups/assign",
        json={"tmux_name": "cloude_x", "group_uuid": a["group_uuid"]},
    )

    body = client.patch(
        f"/api/v1/session-groups/{a['group_uuid']}", json={"name": "renamed"}
    ).json()

    assert _names(body) == ["renamed"]
    assert body["groups"][0]["members"] == ["cloude_x"]


def test_reorder_rewrites_the_whole_order(app_env):
    client, _ = app_env
    client.post("/api/v1/session-groups", json={"name": "a"})
    client.post("/api/v1/session-groups", json={"name": "b"})
    listed = client.post("/api/v1/session-groups", json={"name": "c"}).json()
    uuids = {g["name"]: g["group_uuid"] for g in listed["groups"]}

    body = client.post(
        "/api/v1/session-groups/order",
        json={"group_uuids": [uuids["c"], uuids["a"], uuids["b"]]},
    ).json()

    assert _names(body) == ["c", "a", "b"]




def test_delete_frees_its_sessions_and_reports_how_many(app_env):
    client, state_dir = app_env
    _store(state_dir, "cloude_1", "cloude_2", "cloude_3")
    a = client.post("/api/v1/session-groups", json={"name": "a"}).json()["groups"][0]
    for name in ("cloude_1", "cloude_2", "cloude_3"):
        client.post(
            "/api/v1/session-groups/assign",
            json={"tmux_name": name, "group_uuid": a["group_uuid"]},
        )

    body = client.delete(f"/api/v1/session-groups/{a['group_uuid']}").json()

    assert body["freed"] == 3, (
        "the confirmation dialog quotes this number - a wrong one tells "
        "the user the wrong thing about what they are about to do"
    )
    assert body["groups"] == []
    assert body["status"] == "ok"


def test_delete_of_a_missing_group_is_a_404(app_env):
    client, _ = app_env
    assert client.delete("/api/v1/session-groups/nope").status_code == 404




@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/v1/session-groups", {"name": "x"}),
        ("post", "/api/v1/session-groups/assign", {"tmux_name": "a", "group_uuid": None}),
        ("post", "/api/v1/session-groups/order", {"group_uuids": []}),
    ],
)
def test_a_write_against_a_missing_datastore_is_503(app_env, method, path, payload):
    client, state_dir = app_env
    db_path_for(state_dir).unlink()

    response = getattr(client, method)(path, json=payload)

    assert response.status_code == 503, (
        f"{method.upper()} {path} answered {response.status_code} against a "
        "datastore that does not exist"
    )




def test_every_landed_write_announces_groups_and_a_refused_one_does_not(app_env, monkeypatch):
    from src.core import session_change_notice

    client, state_dir = app_env
    frames = []

    class _Hub:
        def publish(self, frame):
            frames.append(frame)
            return 1

    monkeypatch.setattr(session_change_notice, "get_hub", lambda _state: _Hub())
    (uuid_a,) = _store(state_dir, "carnivore_a")
    created = client.post("/api/v1/session-groups", json={"name": "work"}).json()
    group_uuid = created["groups"][0]["group_uuid"]
    client.patch(f"/api/v1/session-groups/{group_uuid}", json={"name": "play"})
    client.post("/api/v1/session-groups/assign", json={"tmux_name": "carnivore_a", "group_uuid": group_uuid})
    client.post(f"/api/v1/session-groups/{group_uuid}/order", json={"session_uuids": [uuid_a]})
    client.post("/api/v1/session-groups/order", json={"group_uuids": [group_uuid]})
    client.delete(f"/api/v1/session-groups/{group_uuid}")
    assert frames == [{"type": "sessions.changed", "reason": "groups"}] * 6
    frames.clear()
    missing = client.patch("/api/v1/session-groups/no-such-group", json={"name": "x"})
    assert missing.status_code == 404
    assert frames == []
