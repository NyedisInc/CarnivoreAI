
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.projects.by_id_routes import router
from src.core.db import connect, db_path_for
from tests.python.route_tests.harness import add_projects, client_for, point_state_at


@pytest.fixture
def twins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = point_state_at(tmp_path, monkeypatch)
    one, two = add_projects(state, [("twin", tmp_path / "one"), ("other", tmp_path / "two")])
    with closing(connect(db_path_for(state))) as conn, conn:
        conn.execute("UPDATE projects SET display_name = 'twin' WHERE id = ?", (two,))
    return client_for(router), state, one, two


def _row(state: Path, project_id: int):
    with closing(connect(db_path_for(state), create=False)) as conn:
        return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def test_patch_by_id_renames_one_of_two_same_named_projects(twins) -> None:
    client, state, one, two = twins
    resp = client.patch(f"/projects/by-id/{two}", json={"new_name": "second"})
    assert resp.status_code == 200 and resp.json()["id"] == two
    assert _row(state, two)["display_name"] == "second" and _row(state, one)["display_name"] == "twin"
    assert client.patch("/projects/by-id/9999", json={"new_name": "x"}).status_code == 404


def test_archive_then_unarchive_by_id(twins) -> None:
    client, state, one, two = twins
    assert client.post(f"/projects/by-id/{two}/archive").json()["archived_at"]
    assert _row(state, two)["archived_at"] and not _row(state, one)["archived_at"]
    assert client.post(f"/projects/by-id/{two}/unarchive").json()["archived_at"] is None
    assert not _row(state, two)["archived_at"]


def test_delete_by_id_removes_one_row(twins, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.session_roles import check as session_roles_check

    async def _no_check(_state) -> None:
        return None

    monkeypatch.setattr(session_roles_check, "after_change", _no_check)
    client, state, one, two = twins
    client.app.state = SimpleNamespace()
    assert client.delete(f"/projects/by-id/{two}").status_code == 200
    assert _row(state, two) is None and _row(state, one) is not None


def test_move_by_id_plans_through_the_one_move_path(twins, tmp_path: Path) -> None:
    client, state, _one, two = twins
    before = _row(state, two)["root"]
    resp = client.post(f"/projects/by-id/{two}/move", json={"new_root": str(tmp_path / "elsewhere"), "apply": False})
    assert resp.status_code == 200, resp.text
    assert _row(state, two)["root"] == before
    assert client.post("/projects/by-id/9999/move", json={"new_root": str(tmp_path / "e"), "apply": False}).status_code == 404


def test_project_named_by_id_still_reaches_the_name_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.routes import router as full_router

    state = point_state_at(tmp_path, monkeypatch)
    (pid,) = add_projects(state, [("by-id", tmp_path / "p")])
    client = client_for(full_router)
    resp = client.delete("/projects/by-id/image")
    assert resp.status_code != 422, resp.text
    assert resp.status_code == 200, resp.text
    assert client.patch(f"/projects/by-id/{pid}", json={"new_name": "renamed"}).status_code == 200
