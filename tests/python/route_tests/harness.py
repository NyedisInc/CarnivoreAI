
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated


def client_for(*routers: APIRouter, signed_in: bool = True, prefix: str = "") -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix=prefix)
    if signed_in:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def point_state_at(tmp_path: Path, monkeypatch: Any) -> Path:
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state_dir, 4, "0.0.0").status == "ok"
    return state_dir


def add_projects(state_dir: Path, rows: Iterable[tuple[str, Path]]) -> list[int]:
    from src.core.project_writes import create_project

    with closing(connect(db_path_for(state_dir))) as conn:
        return [create_project(conn, name=name, path=str(path))["id"] for name, path in rows]
