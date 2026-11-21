
from __future__ import annotations

from pathlib import Path

import pytest

from src.api import config_files_routes
from tests.python.route_tests.harness import client_for


def _create(client, project: Path, path: str, **extra):
    body = {"root": "workdir", "path": path, "project_path": str(project), **extra}
    return client.post("/config-files/create", json=body)


def test_create_writes_a_new_file_under_the_project(tmp_path: Path) -> None:
    resp = _create(client_for(config_files_routes.router), tmp_path, "notes.md", content="# hi")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True
    assert (tmp_path / "notes.md").read_text() == "# hi"


def test_create_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("original")
    resp = _create(client_for(config_files_routes.router), tmp_path, "keep.md", content="new")
    assert resp.status_code == 400
    assert (tmp_path / "keep.md").read_text() == "original"


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd-copy"])
def test_create_refuses_a_path_that_leaves_the_root(tmp_path: Path, path: str) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    resp = _create(client_for(config_files_routes.router), project, path)
    assert resp.status_code == 400
    assert not (tmp_path / "escape.md").exists()


def test_create_refuses_malformed_json_for_a_json_name(tmp_path: Path) -> None:
    resp = _create(client_for(config_files_routes.router), tmp_path, "bad.json", content="{nope")
    assert resp.status_code == 400
    assert not (tmp_path / "bad.json").exists()


def test_create_needs_auth(tmp_path: Path) -> None:
    resp = _create(client_for(config_files_routes.router, signed_in=False), tmp_path, "x.md")
    assert resp.status_code in (401, 403)
    assert not (tmp_path / "x.md").exists()
