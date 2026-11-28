
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.crosstalk import spawn_peer_folder as pf
from src.core.mcp import federated


def _answer(code: str, status: int = 409) -> SimpleNamespace:
    return SimpleNamespace(status_code=status, json=lambda: {"detail": {"code": code}})


def test_the_refusal_names_the_computer_and_the_folder_and_never_raw_text() -> None:
    reason = pf.refusal_reason("host-b", _answer("working_dir_missing"), 409, "/Users/demo/work/cloudecode")
    assert isinstance(reason, pf.SpawnReason) and "host-b has no folder at /Users/demo/work/cloudecode" in str(reason)
    assert pf.missing_folder(_answer("working_dir is not an existing directory"))
    assert "/Users" not in str(pf.refusal_reason("host-b", _answer("/Users/x/secret path"), 409, "/w"))
    assert "invalid_effort" in str(pf.refusal_reason("host-b", _answer("invalid_effort"), 409, "/w"))


def test_a_peer_is_found_by_label_host_key_bare_key_or_install_id(monkeypatch) -> None:
    peer = SimpleNamespace(key="peer-hostb01", label="host-b", peer_install_id="IID-1")
    monkeypatch.setattr("src.core.federation.peer_hosts.list_peers", lambda conn, include_mesh=True: [peer])
    monkeypatch.setattr("src.api.peer_auth.open_db", lambda: SimpleNamespace(close=lambda: None))
    for name in ("host-b", "HOST-B", "peer-hostb01", "hostb01", "iid-1"):
        assert asyncio.run(federated.find_peer(name)) is peer
    with pytest.raises(pf.SpawnReason, match="no paired computer"):
        asyncio.run(federated.find_peer("nope"))


def test_a_carried_projects_folder_maps_to_the_replica_folder(monkeypatch, tmp_path) -> None:
    import sqlite3

    def fresh(_settings):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE projects (uid TEXT, root TEXT)")
        conn.execute("INSERT INTO projects VALUES ('u1', '/Users/demo/dev/app')")
        return conn

    monkeypatch.setattr("src.api.projects_service.open_db_or_503", fresh)
    monkeypatch.setattr("src.core.pack.identity.replicas.list_replicas", lambda _c, uid: [
        {"install_id": "IID-1", "state": "active", "root": "/Users/demo/carnivore-projects/app"}] if uid == "u1" else [])
    assert pf.replica_folder("/Users/demo/dev/app/src", "IID-1") == "/Users/demo/carnivore-projects/app/src"
    assert pf.replica_folder("/Users/demo/dev/app", "IID-2") is None
    assert pf.replica_folder("/Users/demo/dev/other", "IID-1") is None
