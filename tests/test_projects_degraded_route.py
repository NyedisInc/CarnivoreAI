
from __future__ import annotations

import pytest

from src.core.db import db_path_for
from tests.test_project_authority import REAL_CONFIG_PROJECTS, cfg
from tests.test_projects_authority_route import (  # noqa: F401
    _config_names,
    _db_rows,
    _read_config_projects,
    _write_config,
    app_env,
)




class TestDatastoreUnreachable:

    def test_get_serves_an_empty_list_rather_than_500ing(self, app_env):
        client, state_dir, _ = app_env
        db_path_for(state_dir).unlink()

        response = client.get("/api/v1/projects")

        assert response.status_code == 200
        assert response.json() == []

    def test_authority_says_the_empty_list_means_could_not_read(self, app_env):
        client, state_dir, _ = app_env
        db_path_for(state_dir).unlink()

        body = client.get("/api/v1/projects/authority").json()

        assert body["mode"] == "db_unreadable"
        assert body["writable"] is False
        assert body["degraded"] is True
        assert body["project_count"] == 0
        assert "UNREACHABLE" in body["message"]
        assert "NOT a claim that you have no projects" in body["message"]

    def test_authority_reports_no_diff_surface_at_all(self, app_env):
        client, state_dir, _ = app_env
        db_path_for(state_dir).unlink()

        body = client.get("/api/v1/projects/authority").json()

        assert "diff" not in body
        assert "diff_state" not in body

    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.post(
                "/api/v1/projects", json={"name": "nope", "path": "/tmp/nope"}
            ),
            lambda c: c.patch(
                "/api/v1/projects/CloudeCode", json={"new_name": "nope"}
            ),
            lambda c: c.delete("/api/v1/projects/CloudeCode"),
        ],
        ids=["create", "rename", "delete"],
    )
    def test_every_write_is_refused_with_503(self, app_env, call):
        client, state_dir, _ = app_env
        db_path_for(state_dir).unlink()

        response = call(client)

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "projects_read_only"

    def test_a_refused_write_does_not_touch_config_json(self, app_env):
        client, state_dir, config_file = app_env
        before = config_file.read_text()
        db_path_for(state_dir).unlink()

        client.post("/api/v1/projects", json={"name": "nope", "path": "/tmp/nope"})

        assert config_file.read_text() == before


class TestGuardIsLoadBearing:

    @staticmethod
    def _break_reads(monkeypatch):
        import sqlite3

        def boom(_conn):
            raise sqlite3.DatabaseError("database disk image is malformed")

        monkeypatch.setattr(
            "src.core.project_authority.list_projects_ordered", boom
        )

    def test_the_connection_still_opens_so_only_the_guard_can_refuse(
        self, app_env, monkeypatch
    ):
        from contextlib import closing as _closing

        from src.core.db import connect as _connect

        client, state_dir, _ = app_env
        self._break_reads(monkeypatch)

        with _closing(_connect(db_path_for(state_dir), create=False)):
            pass

        assert client.get("/api/v1/projects/authority").json()["writable"] is False

    def test_a_create_is_refused_by_the_guard_not_by_the_connection(
        self, app_env, monkeypatch
    ):
        client, _, _ = app_env
        self._break_reads(monkeypatch)

        response = client.post(
            "/api/v1/projects", json={"name": "sneaky", "path": "/tmp/sneaky"}
        )

        assert response.status_code == 503

    def test_no_row_is_written_when_the_guard_refuses(self, app_env, monkeypatch):
        client, state_dir, _ = app_env
        self._break_reads(monkeypatch)

        client.post("/api/v1/projects", json={"name": "sneaky", "path": "/tmp/sneaky"})

        monkeypatch.undo()
        assert "sneaky" not in [r["display_name"] for r in _db_rows(state_dir)]

    def test_config_is_untouched_when_the_guard_refuses(self, app_env, monkeypatch):
        client, _, config_file = app_env
        before = config_file.read_text()
        self._break_reads(monkeypatch)

        client.post("/api/v1/projects", json={"name": "sneaky", "path": "/tmp/sneaky"})

        assert config_file.read_text() == before
