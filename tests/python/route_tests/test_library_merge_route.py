
from __future__ import annotations

from pathlib import Path

import pytest

from src.api import library_cleanup_routes
from tests.python.route_tests.harness import add_projects, client_for, point_state_at


@pytest.fixture
def two_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = point_state_at(tmp_path, monkeypatch)
    source, target = add_projects(state, [("src-proj", tmp_path / "a"), ("dst-proj", tmp_path / "b")])
    return client_for(library_cleanup_routes.router), source, target


def _project_ids(client) -> set[int]:
    from contextlib import closing

    from src.config import settings
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(settings.get_state_dir()))) as conn:
        return {r[0] for r in conn.execute("SELECT id FROM projects")}


def test_merge_refuses_two_different_folders_without_the_flag(two_projects) -> None:
    client, source, target = two_projects
    resp = client.post(f"/library/projects/{source}/merge", json={"into": target})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "different_folder"
    assert _project_ids(client) >= {source, target}


def test_merge_with_the_flag_drops_the_source_and_keeps_the_target(two_projects) -> None:
    client, source, target = two_projects
    resp = client.post(f"/library/projects/{source}/merge", json={"into": target, "allow_different_folder": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"]["id"] == source and body["target"]["id"] == target
    ids = _project_ids(client)
    assert target in ids and source not in ids


def test_merge_refuses_a_project_into_itself(two_projects) -> None:
    client, source, _ = two_projects
    resp = client.post(f"/library/projects/{source}/merge", json={"into": source})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "same_project"


def test_merge_unknown_source_is_a_404(two_projects) -> None:
    client, _, target = two_projects
    assert client.post("/library/projects/999999/merge", json={"into": target}).status_code == 404


def test_merge_needs_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    point_state_at(tmp_path, monkeypatch)
    resp = client_for(library_cleanup_routes.router, signed_in=False).post(
        "/library/projects/1/merge", json={"into": 2}
    )
    assert resp.status_code in (401, 403)


def test_merge_refuses_a_source_with_swarm_data_as_409_and_keeps_both_rows(two_projects) -> None:
    from contextlib import closing

    from src.config import settings
    from src.core.db import connect, db_path_for

    client, source, target = two_projects
    with closing(connect(db_path_for(settings.get_state_dir()))) as conn:
        conn.execute("INSERT INTO swarm_project_settings (project_id) VALUES (?)", (source,))
    resp = client.post(f"/library/projects/{source}/merge", json={"into": target, "allow_different_folder": True})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "source_has_swarm_or_pack_data"
    assert _project_ids(client) >= {source, target}
