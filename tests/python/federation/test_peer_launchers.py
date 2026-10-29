
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.routes import router
from src.config import settings
from src.config.launch_profiles import LaunchProfile
from src.core.federation import peer_fanout, peer_launchers
from src.core.federation.peer_fanout import PeerAnswer

STUDIO = "peer-studio"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _profiles(monkeypatch) -> None:
    rows = (LaunchProfile.model_validate({"id": "cld", "label": "cld", "harness": "claude", "flags": ["--verbose"],
                                          "env": [{"name": "MY_FLAG", "value": "x"}]}),)
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: rows)


def test_the_served_summary_is_id_name_family_and_nothing_else(monkeypatch) -> None:
    _profiles(monkeypatch)
    body = _client().get("/api/v1/launchers/summary").json()
    assert body == {"launchers": [{"id": "cld", "name": "cld", "family": "claude"}]}


def test_the_owner_route_asks_only_the_named_computer_and_returns_its_launchers(monkeypatch) -> None:
    seen = {}

    async def fake(path, open_db, links=None, only=None):
        seen.update(path=path, only=only)
        return [PeerAnswer(STUDIO, "studio", {"launchers": [{"id": "claude", "name": "claude", "family": "claude"}]})]

    monkeypatch.setattr(peer_fanout, "ask_peers", fake)
    body = _client().get(f"/api/v1/launchers/computer/{STUDIO}").json()
    assert seen == {"path": "/launchers/summary", "only": STUDIO}
    assert body == {"status": "ok", "launchers": [{"id": "claude", "name": "claude", "family": "claude"}]}


def test_an_old_or_unreachable_computer_is_unavailable_not_an_error(monkeypatch) -> None:
    async def old(path, open_db, links=None, only=None):
        return [PeerAnswer(STUDIO, "studio", None, "http_404")]

    monkeypatch.setattr(peer_fanout, "ask_peers", old)
    assert _client().get(f"/api/v1/launchers/computer/{STUDIO}").json() == {"status": "unavailable", "reason": "http_404"}

    async def none(path, open_db, links=None, only=None):
        return []

    monkeypatch.setattr(peer_fanout, "ask_peers", none)
    assert _client().get("/api/v1/launchers/computer/nobody").json()["reason"] == "not_paired"


def test_a_peer_answer_with_a_stray_field_is_refused_not_shown() -> None:
    bad = PeerAnswer(STUDIO, "studio", {"launchers": [{"id": "a", "name": "a", "family": "claude", "env": [{"name": "K"}]}]})
    assert peer_launchers.shown_for([bad]) == {"status": "unavailable", "reason": "bad_answer"}


def test_an_ssh_computer_offers_exactly_the_families_ssh_can_start(monkeypatch) -> None:
    from src.api import launchers_peer_routes
    from src.core.sessions.remote_sessions import remote_command

    async def none(path, open_db, links=None, only=None):
        return []

    monkeypatch.setattr(peer_fanout, "ask_peers", none)
    monkeypatch.setattr(launchers_peer_routes, "_is_ssh_host", lambda key: key == "box")
    body = _client().get("/api/v1/launchers/computer/box").json()
    assert body["status"] == "ssh"
    for family in ("claude", "codex", "hermes", "openclaw", "shell"):
        accepted = True
        try:
            remote_command({"claude": "/c", "codex": "/x"}, "box", family, None, None)
        except ValueError:
            accepted = False
        assert (family in body["families"]) == accepted


def test_a_non_local_non_ssh_peer_is_not_treated_as_ssh(monkeypatch) -> None:
    import sqlite3
    from types import SimpleNamespace

    from src.api import launchers_peer_routes
    from src.core.hosts import store

    monkeypatch.setattr(launchers_peer_routes.peer_auth, "open_db", lambda: sqlite3.connect(":memory:"))
    for kind, expected in (("peer", False), ("ssh", True)):
        monkeypatch.setattr(store, "get_host", lambda conn, key, kind=kind: SimpleNamespace(kind=kind, is_local=False))
        assert launchers_peer_routes._is_ssh_host("box") is expected
