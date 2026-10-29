
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_replica_routes as peer_routes  # noqa: E402
from src.api import peer_auth, recreate_action  # noqa: E402
from src.api.peer_auth import OWNER  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.pack.identity import home, replicas  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402

PEER_INSTALL = "iid-home-a"
ROOT_A = "/work/trader"


def _machine(monkeypatch, tmp_path: Path, name: str) -> Path:
    state = tmp_path / name
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    return state


def _conn(state: Path):
    return connect(db_path_for(state), create=False)


def _seed_home(state: Path) -> dict:
    with closing(_conn(state)) as conn:
        conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Acme', 't', 't')")
        cid = conn.execute("SELECT id FROM companies WHERE name = 'Acme'").fetchone()[0]
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, company_id, created_at, updated_at) "
                     "VALUES (?, ?, 'trader', 'user', ?, 't', 't')", (ROOT_A, ROOT_A, cid))
        conn.commit()
        return dict(conn.execute("SELECT * FROM projects WHERE display_name = 'trader'").fetchone())


def test_uid_is_stamped_the_lock_refuses_create_and_wake_and_a_replica_shares_the_uid(monkeypatch, tmp_path) -> None:
    a = _machine(monkeypatch, tmp_path, "a")
    project = _seed_home(a)
    uid = project["uid"]
    assert uid and len(uid) == 32 and project["pack_state"] == "home"
    with closing(_conn(a)) as conn:
        assert conn.execute("SELECT uid FROM companies WHERE name = 'Acme'").fetchone()[0]
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                     "VALUES ('/x', '/x', 'other', 'user', 't', 't')")
        conn.commit()
        uids = [r[0] for r in conn.execute("SELECT uid FROM projects")]
        assert len(set(uids)) == len(uids) == 2

    asyncio.run(home.require_active(ROOT_A))
    with closing(_conn(a)) as conn:
        home.set_state(conn, project["id"], "moved_away", moved_to_install_id="iid-b")
    asyncio.run(home.require_active("/work/elsewhere"))

    manager = SessionManager.__new__(SessionManager)
    for folder in (ROOT_A, ROOT_A + "/sub/dir"):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(manager.create_session("ses_x", working_dir=folder))
        assert refused.value.status_code == 409 and refused.value.detail["code"] == "project_moved_away"
        assert refused.value.detail["moved_to"] == "iid-b"

    def gather(_uuid, _overrides, fresh=False, corpus_root=None):
        return {"row": {"session_uuid": "u1", "working_dir": ROOT_A}, "name": "cloude_t", "presence": None}

    monkeypatch.setattr(recreate_action.rr, "_gather", gather)
    with pytest.raises(HTTPException) as woken:
        asyncio.run(recreate_action.recreate_by_uuid("u1", "claude", get_manager=lambda: manager))
    assert woken.value.status_code == 409 and woken.value.detail["code"] == "project_moved_away"

    with closing(_conn(a)) as conn:
        home.set_state(conn, project["id"], "home")
    asyncio.run(home.require_active(ROOT_A))

    b = _machine(monkeypatch, tmp_path, "b")
    with closing(_conn(b)) as conn:
        key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grants.create_grant(conn, peer_install_id=PEER_INSTALL, public_key=key, label="a", scopes=("replica",))
        grant = grants.list_grants(conn)[0]
    app = FastAPI()
    app.include_router(peer_routes.router, prefix="/api/v1")
    app.dependency_overrides[peer_routes._require_replica] = lambda: peer_auth.Principal("peer", grant)
    client = TestClient(app)
    body = {"project_uid": uid, "name": "trader", "root": str(tmp_path / "b-trader"), "company_uid": None, "company_name": "Acme"}
    ok = client.post("/api/v1/federation/pack/replica", json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["project_uid"] == uid and ok.json()["state"] == "replica" and ok.json()["created"] is True
    with closing(_conn(b)) as conn:
        row = dict(conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone())
    assert row["pack_state"] == "replica" and row["home_install_id"] == PEER_INSTALL
    assert Path(row["root"]).is_dir()
    assert client.post("/api/v1/federation/pack/replica", json=body).json()["created"] is False

    other = {**body, "project_uid": "f" * 32}
    taken = client.post("/api/v1/federation/pack/replica", json={**other, "root": str(tmp_path / "b-other")})
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "project_name_taken"
    in_use = client.post("/api/v1/federation/pack/replica", json=other)
    assert in_use.status_code == 409 and in_use.json()["detail"]["code"] == "project_root_in_use"

    app.dependency_overrides[peer_routes._require_replica] = lambda: OWNER
    assert client.post("/api/v1/federation/pack/replica", json=body).status_code == 403

    with closing(_conn(b)) as conn:
        assert replicas.detach_replica(conn, home_install_id=PEER_INSTALL, project_uid=uid) is True
        detached = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone())
    assert detached["pack_state"] == "home" and detached["uid"] != uid and Path(detached["root"]).is_dir()
