
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ruff: noqa: E402
from src.api import pack_allow_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated


def _client(tmp_path: Path, monkeypatch, auth: bool = True) -> TestClient:
    assert ensure_db_migrated(tmp_path).status == "ok"
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    app = FastAPI()
    app.include_router(pack_allow_routes.router, prefix="/api/v1")
    if auth:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def _seed(tmp_path: Path) -> None:
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Acme', 't', 't')")
        cid = conn.execute("SELECT id FROM companies").fetchone()[0]
        for root, name, company, extra in (("/s/home", "alpha", cid, ""), ("/s/copy", "beta", cid, ""), ("/s/old", "old", cid, "arch"),
                                           ("/s/gone", "gone", cid, "moved"), ("/s/solo", "solo", None, "")):
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, company_id, created_at, updated_at, archived_at) "
                         "VALUES (?, ?, ?, 'user', ?, 't', 't', ?)", (root, root, name, company, "t" if extra == "arch" else None))
        conn.execute("UPDATE projects SET pack_state = 'replica', home_install_id = 'iid-x' WHERE display_name = 'beta'")
        conn.execute("UPDATE projects SET pack_state = 'moved_away', moved_to_install_id = 'iid-y' WHERE display_name = 'gone'")
        conn.commit()


def test_choices_are_live_projects_with_the_rule_uids_and_no_path(tmp_path: Path, monkeypatch) -> None:
    c = _client(tmp_path, monkeypatch)
    _seed(tmp_path)
    body = c.get("/api/v1/pack/allow-choices").json()
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        cuid = conn.execute("SELECT uid FROM companies").fetchone()[0]
        puid = {r[0]: r[1] for r in conn.execute("SELECT display_name, uid FROM projects")}
    assert cuid and all(puid.values())
    assert body["companies"] == [{"uid": cuid, "name": "Acme"}]
    assert body["projects"] == [{"uid": puid["alpha"], "name": "alpha", "company_uid": cuid},
                                {"uid": puid["beta"], "name": "beta", "company_uid": cuid},
                                {"uid": puid["solo"], "name": "solo", "company_uid": None}]
    assert "/s/" not in c.get("/api/v1/pack/allow-choices").text


def test_401_without_auth(tmp_path: Path, monkeypatch) -> None:
    c = _client(tmp_path, monkeypatch, auth=False)
    assert c.get("/api/v1/pack/allow-choices").status_code in (401, 403)
