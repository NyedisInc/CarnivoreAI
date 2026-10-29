
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.api import blueprints_launch as steps
from src.api import blueprints_peer_member as member_mod
from src.api import peer_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, peer_links, shadow_rows
from src.models.blueprints import BlueprintSession

IID = "iid-studio"


class Client:
    def __init__(self):
        self.calls = []

    async def request(self, method, path, *, json=None, timeout=None):
        self.calls.append((method, path, json))
        if method == "POST":
            body, status = {"id": "ses_far1"}, 201
        else:
            body, status = {"tmux_session": "carnivore_bp"}, 200
        return SimpleNamespace(status_code=status, body=__import__("json").dumps(body).encode(),
                               headers={"content-type": "application/json"}, json=lambda: body)


class Links:
    def __init__(self, client):
        self._client = client

    def client(self, _iid):
        return self._client

    def minor(self, _iid):
        return 0


@pytest.fixture()
def world(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    monkeypatch.setattr(member_mod, "SHADOW_WAIT_SECONDS", 1.0)
    with closing(connect(path, create=False)) as conn:
        peer = peer_hosts.upsert(conn, install_id=IID, label="studio", grant_id="g", fid="f", initiator=True,
                                 ssh_target="studio")
        conn.execute("UPDATE hosts SET peer_state = 'connected' WHERE key = ?", (peer.key,))
        shadow = shadow_rows.sync_peer(conn, host_key=peer.key, peer_install_id=IID, complete=True, rows=[{
            "session_uuid": "11111111-2222-4333-8444-555555555555", "row_id": 9, "name": "carnivore_bp",
            "working_dir": "/far", "label": "bp"}])
    client = Client()
    monkeypatch.setattr(peer_links, "LINKS", Links(client))
    return SimpleNamespace(key=peer.key, client=client, shadow_id=shadow["carnivore_bp"].session_id, mp=monkeypatch)


def spec(key, **extra):
    folder = extra.pop("folder", {"mode": "existing", "path": "/far"})
    return BlueprintSession(label="bp", family="shell", folder=folder, host_key=key, **extra)


def launch(member):
    return asyncio.run(steps.launch_member(None, 0, member, "/root", {}, None, None))


def test_a_member_is_created_on_the_peer_and_keyed_on_its_shadow_row(world):
    out = launch(spec(world.key))
    assert out.state == "launched"
    assert out.session.id == f"remote:{world.key}:carnivore_bp" and out.session.session_row_id == world.shadow_id
    method, path, body = world.client.calls[0]
    assert (method, path) == ("POST", "/sessions") and body["host_key"] == "local" and body["working_dir"] == "/far"


def test_a_down_peer_fails_that_member_by_name(world):
    world.mp.setattr(peer_links, "LINKS", Links(None))
    out = launch(spec(world.key))
    assert out.state == "failed" and out.problem.step == "session" and out.problem.code == "peer_unavailable"


def test_an_unknown_peer_and_unsupported_parts_are_named(world):
    assert launch(spec("peer-nobody")).problem.code == "peer_unknown"
    wt = {"mode": "worktree", "repo_path": "/r", "base_branch": "main", "branch": "b"}
    assert launch(spec(world.key, folder=wt)).problem.code == "peer_worktree_unsupported"
    assert launch(spec(world.key, skills=["pub/name"])).problem.code == "peer_skills_unsupported"
    assert world.client.calls == []


def test_a_local_key_means_this_mac():
    assert spec("local").host_key is None
