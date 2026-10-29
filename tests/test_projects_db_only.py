
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dbo_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dbo_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.project_store import import_from_config


def cfg(name: str, path: str, description=None):
    return SimpleNamespace(
        name=name, path=path, description=description, agent_type=None
    )


def write_config_with_projects(path: Path, entries) -> None:
    path.write_text(
        json.dumps(
            {
                "config_version": 4,
                "template_path": "claude-template",
                "projects": [
                    {
                        "name": e.name,
                        "path": e.path,
                        "description": e.description,
                    }
                    for e in entries
                ],
            },
            indent=2,
        )
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_file = tmp_path / "config.json"

    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    monkeypatch.setattr(
        settings, "auth_config_file", str(config_file), raising=False
    )
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)

    assert ensure_db_migrated(state_dir, 4, "0.0.0").status == "ok"
    return SimpleNamespace(state_dir=state_dir, config_file=config_file)


def client_for() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


class TestConfigProjectsAreInert:

    def test_config_projects_do_not_reach_the_served_list(self, env):
        write_config_with_projects(
            env.config_file,
            [
                cfg("alpha", "/tmp/alpha"),
                cfg("beta", "/tmp/beta"),
                cfg("gamma", "/tmp/gamma"),
                cfg("delta", "/tmp/delta"),
            ],
        )
        from src.config import settings

        settings._auth_config_cache = None

        with client_for() as client:
            body = client.get("/api/v1/projects").json()

        assert body == [], (
            "config.json's projects key was resurrected into the served "
            f"list; projects are DB-only now. Got: {body}"
        )

    def test_auth_config_has_no_projects_attribute(self, env):
        from src.config import settings

        settings._auth_config_cache = None
        write_config_with_projects(env.config_file, [cfg("alpha", "/tmp/alpha")])
        loaded = settings.load_auth_config()

        assert not hasattr(loaded, "projects"), (
            "AuthConfig still carries a projects attribute, so config is "
            "still a project source"
        )


class TestDivergenceMachineryIsAbsent:

    def test_project_diff_module_is_gone(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.core.project_diff")

    def test_project_snapshot_module_is_gone(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.core.project_snapshot")

    def test_authority_has_no_config_comparing_surface(self):
        from src.core import project_authority as authority

        for gone in (
            "MODE_DB_EMPTY_CONFIG_HAS",
            "MODE_CONFIG_FALLBACK",
            "refresh_snapshot",
        ):
            assert not hasattr(authority, gone), (
                f"{gone} survives; the config-comparison path is still "
                "reachable"
            )

    def test_authority_payload_carries_no_diff(self, env):
        write_config_with_projects(env.config_file, [cfg("alpha", "/tmp/alpha")])
        from src.config import settings

        settings._auth_config_cache = None

        with client_for() as client:
            body = client.get("/api/v1/projects/authority").json()

        for gone in ("diff", "diff_state", "config_path"):
            assert gone not in body, (
                f"authority payload still carries '{gone}'; the "
                f"comparison surface is still live. Body keys: "
                f"{sorted(body)}"
            )


class TestDatastoreUnreadableIsItsOwnOutcome:

    def test_unreadable_db_is_named_and_refuses_writes(self, env, monkeypatch):
        from src.core import project_authority as authority

        def boom(*args, **kwargs):
            raise OSError("disk gone")

        monkeypatch.setattr(authority, "connect", boom, raising=True)
        view = authority.resolve_projects(env.state_dir)

        assert view.mode == authority.MODE_DB_UNREADABLE
        assert view.projects == []
        assert view.writable is False
        assert "not" in view.message.lower(), (
            "the unreadable-datastore message must explicitly deny that "
            f"this means zero projects. Got: {view.message!r}"
        )

    def test_resolve_projects_takes_no_config_argument(self, env):
        import inspect

        from src.core import project_authority as authority

        allowed = {"state_dir", "include_archived"}
        params = list(
            inspect.signature(authority.resolve_projects).parameters
        )
        assert params[0] == "state_dir", (
            f"resolve_projects no longer leads with state_dir: {params}"
        )
        extra = [p for p in params if p not in allowed]
        assert not extra, (
            f"resolve_projects accepts {extra}; it must read only the "
            "datastore, so it may take the state dir and read FILTERS "
            "over it, never another source of projects"
        )


class TestUpgradeMigration:

    def test_config_only_projects_are_imported_then_key_dropped(self, env):
        from src.core.projects_config_migration import migrate_projects_out_of_config

        write_config_with_projects(
            env.config_file,
            [cfg("only-in-config", "/tmp/only-in-config")],
        )

        result = migrate_projects_out_of_config(
            env.state_dir, env.config_file
        )

        assert result.ok is True
        assert [e["name"] for e in result.imported] == ["only-in-config"]

        doc = json.loads(env.config_file.read_text())
        assert "projects" not in doc, (
            "the legacy projects key survived a successful migration"
        )

        with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT display_name FROM projects"
                ).fetchall()
            ]
        assert names == ["only-in-config"]

    def test_deleted_projects_are_not_resurrected_by_the_migration(self, env):
        from src.core.project_tombstones import record_tombstone
        from src.core.projects_config_migration import (
            migrate_projects_out_of_config,
        )

        write_config_with_projects(
            env.config_file, [cfg("removed", "/tmp/removed")]
        )
        with closing(connect(db_path_for(env.state_dir))) as conn:
            with transaction(conn):
                import_from_config(conn, [cfg("removed", "/tmp/removed")])
                row = conn.execute(
                    "SELECT id, root FROM projects"
                ).fetchone()
                conn.execute("DELETE FROM projects WHERE id = ?", (row[0],))
                record_tombstone(conn, row[1], "removed")

        result = migrate_projects_out_of_config(env.state_dir, env.config_file)

        assert result.imported == []
        assert [e["root"] for e in result.skipped_deleted] == ["/tmp/removed"]
        assert "projects" not in json.loads(env.config_file.read_text())

    def test_migration_keeps_the_key_when_it_cannot_prove_coverage(
        self, env, monkeypatch
    ):
        from src.core import projects_config_migration as mig

        write_config_with_projects(env.config_file, [cfg("alpha", "/tmp/alpha")])
        before = env.config_file.read_text()

        def boom(*args, **kwargs):
            raise OSError("disk gone")

        monkeypatch.setattr(mig, "connect", boom, raising=True)
        result = mig.migrate_projects_out_of_config(
            env.state_dir, env.config_file
        )

        assert result.ok is False
        assert result.reason == "datastore_unreadable"
        assert env.config_file.read_text() == before

    def test_unexplained_roots_are_imported_and_named_not_dropped(self, env):
        from src.core.projects_config_migration import (
            migrate_projects_out_of_config,
        )

        write_config_with_projects(
            env.config_file, [cfg("ambiguous", "/tmp/ambiguous")]
        )
        with closing(connect(db_path_for(env.state_dir))) as conn:
            conn.execute("DROP TABLE IF EXISTS project_tombstones")
            conn.commit()

        result = migrate_projects_out_of_config(env.state_dir, env.config_file)

        assert result.ok is True
        assert [e["name"] for e in result.imported_undetermined] == ["ambiguous"]
        assert result.imported == [], (
            "an unexplained root must be reported separately from a clean "
            "import, not folded in with it"
        )
        assert "CANNOT BE DETERMINED" in (result.notice() or "")
        assert "projects" not in json.loads(env.config_file.read_text())

    def test_a_forwarding_note_replaces_the_retired_key(self, env):
        from src.core.projects_config_migration import (
            migrate_projects_out_of_config,
        )

        write_config_with_projects(env.config_file, [cfg("alpha", "/tmp/alpha")])
        migrate_projects_out_of_config(env.state_dir, env.config_file)

        doc = json.loads(env.config_file.read_text())
        note = doc.get("_comment_projects_retired")
        assert isinstance(note, str) and "cloude.db" in note
        assert "does nothing" in note, (
            "the note must say that re-adding the key has no effect, not "
            "merely that projects moved"
        )
