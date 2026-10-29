
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_co_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_co_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.api.auth_routes import router as auth_router  # noqa: E402
from src.api.routes import router as api_router  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.project_writes import create_project  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    db = db_path_for(state)
    with closing(connect(db)) as conn:
        a = create_project(conn, name="alpha", path=str(tmp_path / "alpha"))
        b = create_project(conn, name="beta", path=str(tmp_path / "beta"))
    return SimpleNamespace(state_dir=state, db=db, ids={"alpha": a["id"], "beta": b["id"]})


@pytest.fixture
def client(world) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)
