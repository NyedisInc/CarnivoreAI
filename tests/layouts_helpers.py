
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Tuple

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lay_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lay_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.layouts_routes import router as layouts_router
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from tests.lifecycle_helpers import add_row


def row(n: int) -> str:
    return f"terminal:row:{n}"


def grid(*cells: str, groups: Dict[str, List[str]] | None = None) -> Dict[str, Any]:
    share = 1 / len(cells) if cells else 1
    layout = {
        "v": 6,
        "rows": [{"id": "r1", "kind": "flex", "size": 1,
                  "slots": [{"id": c, "fr": share} for c in cells]}],
        "hidden": [], "heroCollapsed": False, "collapsed": [],
    }
    return {"layout": layout, "groups": {k: {"tabs": v} for k, v in (groups or {}).items()}}


def migrated(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    assert ensure_db_migrated(state_dir).status == "ok"
    return db_path_for(state_dir)


def add_sessions(db_path: Path, count: int, prefix: str = "u") -> List[Tuple[int, str]]:
    out = []
    with closing(connect(db_path, create=False)) as conn:
        for i in range(count):
            uuid = f"{prefix}{i}-0000"
            out.append((add_row(conn, uuid=uuid, name=f"cloude_{prefix}{i}", epoch=1000 + i), uuid))
    return out


def client_for(tmp_path: Path, monkeypatch) -> Tuple[TestClient, Path, List[Dict[str, Any]]]:
    from src.config import settings
    from src.core import session_change_notice

    state_dir = tmp_path / "state"
    db_path = migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    frames: List[Dict[str, Any]] = []
    monkeypatch.setattr(session_change_notice, "publish",
                        lambda state, frame: frames.append(frame))
    app = FastAPI()
    app.include_router(layouts_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app), db_path, frames
