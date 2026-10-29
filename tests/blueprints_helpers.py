
from __future__ import annotations

import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.blueprints_routes import router as blueprints_router
from src.api.layouts_routes import router as layouts_router
from src.api.session_crud_routes import router as sessions_router
from src.core.db import connect, db_path_for
from src.core.sessions.theme_store import ThemeStore
from src.models import Session
from tests.helpers.catalog_app import StateOnlySettings, register_projects
from tests.lifecycle_helpers import SOCKET, add_row
from tests.test_skill_installer import FakeInstallRoots


def git(*args: str, cwd: Optional[Path] = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def make_repo(path: Path, *, branch: str = "master") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", branch, str(path))
    git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "-C", str(path),
        "commit", "-q", "--allow-empty", "-m", "init")
    return path.resolve()


def member(label: str, path: Any, **extra: Any) -> Dict[str, Any]:
    body = {"label": label, "family": "claude", "folder": {"mode": "existing", "path": str(path)}}
    body.update(extra)
    return body


def spec(name: str, *sessions: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    body = {"name": name, "sessions": list(sessions)}
    body.update(extra)
    return body


class RecordingManager:

    def __init__(self, db_path: Path, fail_labels: tuple = ()) -> None:
        self.db_path = db_path
        self.fail_labels = set(fail_labels)
        self.calls: List[Dict[str, Any]] = []
        self.names: List[Dict[str, str]] = []
        self.live: List[int] = []
        self.themes = ThemeStore(pin_path=lambda: db_path.parent / "pinned_themes.json")

    def set_pinned_theme(self, tmux_name: str, theme_id: Optional[str]) -> None:
        self.themes.set_pin(tmux_name, theme_id)

    async def list_session_infos(self) -> List[Any]:
        out: List[Any] = []
        with closing(connect(self.db_path, create=False)) as conn:
            for row_id in self.live:
                r = conn.execute("SELECT title, tmux_name, working_dir FROM sessions WHERE id = ?",
                                 (row_id,)).fetchone()
                out.append(SimpleNamespace(
                    session_row_id=row_id, tmux_session=r[1], label=r[0],
                    session=SimpleNamespace(id=f"ses_{row_id}", working_dir=r[2])))
        return out

    def active_tmux_names(self) -> set:
        return {c["name"] for c in self.names}

    def list_attachable_sessions(self) -> list:
        return []

    def tmux_socket_name(self) -> str:
        return SOCKET

    async def create_session(self, session_id: str, **kwargs: Any) -> Session:
        self.calls.append({"session_id": session_id, **kwargs})
        if kwargs.get("label") in self.fail_labels:
            raise RuntimeError("agent failed to launch: test double")
        name = f"cloude_{kwargs.get('project_name')}_{len(self.calls)}"
        self.names.append({"name": name})
        epoch = 5000 + len(self.calls)
        with closing(connect(self.db_path, create=False)) as conn:
            row_id = add_row(conn, uuid=f"bp-{len(self.calls)}", name=name, epoch=epoch)
            conn.execute("UPDATE sessions SET working_dir = ?, title = ?, agent_type = ? "
                         "WHERE id = ?", (kwargs.get("working_dir"), kwargs.get("label"),
                                          kwargs.get("agent_type"), row_id))
            conn.commit()
        return Session(id=session_id, working_dir=kwargs.get("working_dir") or "/",
                       tmux_session=name, tmux_created_epoch=epoch)


def patch_settings(monkeypatch, state: Path, config_path: Path, wrappers: list = ()) -> None:
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    fake = SimpleNamespace(agents=SimpleNamespace(wrappers=list(wrappers)))
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: fake, raising=True)


def mount(app: FastAPI, manager: RecordingManager) -> None:
    app.include_router(blueprints_router, prefix="/api/v1")
    app.include_router(layouts_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = manager


def client_for(tmp_path: Path, monkeypatch, *, projects: tuple = (), fail_labels: tuple = (),
               wrappers: list = ()) -> SimpleNamespace:
    from src.core import session_change_notice

    state = tmp_path / "state"
    db = migrated(state)
    config = tmp_path / "config.json"
    config.write_text("{}\n", encoding="utf-8")
    patch_settings(monkeypatch, state, config, wrappers)
    if projects:
        register_projects(state, projects)
    frames: List[Dict[str, Any]] = []
    monkeypatch.setattr(session_change_notice, "publish", lambda s, f: frames.append(f))
    roots = FakeInstallRoots(tmp_path / "roots")
    roots.make_roots()
    manager = RecordingManager(db, fail_labels)
    app = FastAPI()
    mount(app, manager)
    from src.core.sessions.background_store import SessionBackgroundStore
    app.state.session_background_store = SessionBackgroundStore(path=lambda: state / "session_backgrounds.json")
    app.state.services = SimpleNamespace(install_roots=roots, themes=manager.themes,
                                         owned_tmux=SimpleNamespace(names=set()),
                                         settings_reader=StateOnlySettings(state))
    return SimpleNamespace(client=TestClient(app), db=db, state=state, manager=manager,
                           frames=frames, config=config)


def db_for(state: Path) -> Path:
    return db_path_for(state)
