
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.federation.test_federation_route_inventory import app, peer_bearer  # noqa: F401
from fastapi.testclient import TestClient

from src.api import filesystem_peer_routes, peer_auth
from src.api.auth import require_auth
from src.config import settings
from src.core.federation import project_folder_browse
from src.core.federation import grants, peer_fanout, peer_folders, peer_links


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for name in ("projects", "code", ".secret", ".ssh", ".claude/projects", ".carnivore/accounts", "Library/Keychains", "code/.git"):
        (home / name).mkdir(parents=True)
    (home / "notes.txt").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(home / "code", home / "link_in")
    os.symlink(outside, home / "link_out")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: home / "projects")
    return home


def _get(peer_bearer, path):
    return TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/filesystem/project-folders", params={"path": path}, headers={"Authorization": f"Bearer {peer_bearer}"})


def test_a_sessions_peer_sees_only_directories_inside_the_far_roots(peer_bearer, tree) -> None:
    r = _get(peer_bearer, str(tree))
    assert r.status_code == 200, r.text
    body = r.json()
    assert {e["name"] for e in body["entries"]} == {"code", "link_in", "projects"}
    assert {e["name"]: e["path"] for e in body["entries"]}["link_in"] == os.path.realpath(tree / "code")
    assert body["parent"] is None


def test_traversal_and_symlink_escape_are_refused_before_existence(peer_bearer, tree) -> None:
    for bad in (f"{tree}/code/../..", "/", f"{tree}/link_out", "/no/such/dir"):
        r = _get(peer_bearer, bad)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "outside_allowed_roots", bad
    r = _get(peer_bearer, f"{tree}/missing")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_a_grant_without_the_sessions_scope_is_refused(peer_bearer, tree) -> None:
    with closing(peer_auth.open_db()) as conn:
        gid = conn.execute("SELECT grant_id FROM federation_grants").fetchone()[0]
        assert grants.set_scopes(conn, gid, ("settings",))
    assert _get(peer_bearer, str(tree)).status_code == 401


def test_the_owner_route_never_asks_an_old_computer_and_refuses_a_peer_token(peer_bearer, monkeypatch) -> None:
    monkeypatch.setattr(filesystem_peer_routes, "_peer_for",
                        lambda key: SimpleNamespace(key="peer-studio", peer_install_id="iid", label="studio"))
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda iid: object(), minor=lambda iid: 3))

    async def boom(*a, **k):
        raise AssertionError("an old computer must never be asked")

    monkeypatch.setattr(peer_fanout, "ask_peers", boom)
    app.dependency_overrides[require_auth] = lambda: None
    try:
        r = TestClient(app, raise_server_exceptions=False).get("/api/v1/filesystem/computer/peer-studio/browse")
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert r.json() == {"status": "unavailable", "reason": "peer_too_old"}
    r = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/filesystem/computer/peer-studio/browse", headers={"Authorization": f"Bearer {peer_bearer}"})
    assert r.status_code == 401


def test_hidden_folders_and_library_are_refused_like_an_outside_path(peer_bearer, tree) -> None:
    outside = _get(peer_bearer, "/")
    for hidden in (".ssh", ".claude/projects", ".carnivore/accounts", "Library/Keychains", "Library", "code/.git", ".secret"):
        r = _get(peer_bearer, str(tree / hidden))
        assert (r.status_code, r.json()) == (outside.status_code, outside.json()), hidden
    os.symlink(tree / ".ssh", tree / "link_hidden")
    assert "link_hidden" not in {e["name"] for e in _get(peer_bearer, str(tree)).json()["entries"]}


def test_a_scan_past_its_time_budget_returns_what_it_gathered_cut_short(tree, monkeypatch) -> None:
    for i in range(20):
        (tree / "projects" / f"d{i}").mkdir()
    monkeypatch.setattr(project_folder_browse, "SCAN_BUDGET_SECONDS", -1.0)
    listing = project_folder_browse.list_project_folders(str(tree / "projects"), settings)
    assert listing.truncated is True and len(listing.entries) < 20


def test_listings_past_the_concurrency_cap_answer_busy_and_the_owner_maps_it(peer_bearer, tree, monkeypatch) -> None:
    monkeypatch.setattr(filesystem_peer_routes, "_listing_slots", asyncio.Semaphore(0))
    r = _get(peer_bearer, str(tree))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "busy"
    assert peer_folders.shown_for([peer_fanout.PeerAnswer("k", "studio", None, "http_503")]) == {"status": "unavailable", "reason": "busy"}


def test_the_owner_side_tells_the_far_403_reasons_apart() -> None:
    def shown(code: str):
        return peer_folders.shown_for([peer_fanout.PeerAnswer("k", "studio", None, "http_403", code)])
    assert shown("outside_allowed_roots") == {"status": "refused", "code": "outside_allowed_roots"}
    assert shown("computer_one_way") == {"status": "unavailable", "reason": "one_way"}
    assert shown("") == {"status": "unavailable", "reason": "refused"}
