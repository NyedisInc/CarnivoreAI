
from __future__ import annotations

import dataclasses
import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from fastapi.testclient import TestClient

from src.api import peer_auth
from src.api.auth import require_auth
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.federation import fed_key, grants, peer_forward, peer_hosts, peer_links, peer_listing, peer_token, shadow_rows
from src.core.federation.peer_client import PeerUnreachable
from src.main import app

PEER_IID = "iid-hosta"
OWNER_UUID = "11111111-2222-4333-8444-555555555555"


class FakeClient:
    def __init__(self, answers):
        self.calls, self.answers = [], answers

    async def request(self, method, path, *, json=None, timeout=None, content=None, headers=None):
        self.calls.append((method, path, json, timeout))
        self.raw = (content, headers)
        answer = self.answers.get((method, path.split("?")[0]), (200, {"ok": True}))
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status_code=answer[0], body=__import__("json").dumps(answer[1]).encode(),
                               headers={"content-type": "application/json"}, json=lambda: answer[1])


class FakeLinks:
    def __init__(self, client, minor=0):
        self._client, self._minor = client, minor

    def client(self, _iid):
        return self._client

    def minor(self, _iid):
        return self._minor


@pytest.fixture()
def world(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        peer = peer_hosts.upsert(conn, install_id=PEER_IID, label="hosta", grant_id="g", fid="f", initiator=True,
                                 ssh_target="hosta")
        conn.execute("UPDATE hosts SET peer_state = 'connected' WHERE key = ?", (peer.key,))
        shadow_rows.sync_peer(conn, host_key=peer.key, peer_install_id=PEER_IID, complete=True,
                              rows=[{"session_uuid": OWNER_UUID, "row_id": 7, "name": "carnivore_api", "working_dir": "/w"}])
        shadow_uuid = conn.execute("SELECT session_uuid FROM sessions WHERE origin = 'peer'").fetchone()[0]
        install_id = get_meta(conn, "install_id")
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([5]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-caller", public_key=pub, label="caller")
    manager = SimpleNamespace(set_session_label=lambda *a: pytest.fail("a LOCAL row was touched"))
    monkeypatch.setattr(app.state, "session_manager", manager, raising=False)
    client = FakeClient({})
    monkeypatch.setattr(peer_links, "LINKS", FakeLinks(client))
    app.dependency_overrides[require_auth] = lambda: None
    yield SimpleNamespace(http=TestClient(app, raise_server_exceptions=False), client=client, key=peer.key,
                          shadow_uuid=shadow_uuid, wire=f"remote:{peer.key}:carnivore_api",
                          peer_bearer=peer_token.mint(grant, install_id)[0], monkeypatch=monkeypatch)
    app.dependency_overrides.pop(require_auth, None)


def test_rename_goes_to_the_owner_only(world) -> None:
    world.client.answers[("PATCH", "/sessions/carnivore_api/name")] = (200, {"renamed": True, "label": "shiny"})
    world.client.answers[("PATCH", "/sessions/ses_owner9/name")] = (200, {"renamed": True, "label": "shiny"})
    world.monkeypatch.setitem(peer_listing._OWNER_IDS, world.key, {"carnivore_api": "ses_owner9"})
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "shiny"})
    assert reply.status_code == 200 and reply.json() == {"renamed": True, "label": "shiny"}
    assert world.client.calls == [("PATCH", "/sessions/ses_owner9/name", {"new_name": "shiny"}, None)]


def test_the_owners_refusal_comes_back_as_it_is(world) -> None:
    world.client.answers[("PATCH", "/sessions/carnivore_api/name")] = (400, {"detail": "too long"})
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert (reply.status_code, reply.json()) == (400, {"detail": "too long"})


def test_a_uuid_route_uses_the_owners_uuid_and_is_slow_tolerant(world) -> None:
    reply = world.http.post(f"/api/v1/sessions/{world.shadow_uuid}/restart")
    assert reply.status_code == 200
    method, path, body, timeout = world.client.calls[0]
    assert (method, path, body) == ("POST", f"/sessions/{OWNER_UUID}/restart", None)
    assert timeout == peer_forward.SLOW_SECONDS


def test_query_and_body_ids_are_swapped(world) -> None:
    world.http.get("/api/v1/sessions/restart/preview", params={"session_name": world.wire})
    world.http.post("/api/v1/sessions/respawn", json={"session_name": world.wire, "confirm_restart_live": True})
    world.http.post("/api/v1/sessions/recreate", json={"session_uuid": world.shadow_uuid})
    assert [c[:3] for c in world.client.calls] == [
        ("GET", "/sessions/restart/preview?session_name=carnivore_api", None),
        ("POST", "/sessions/respawn", {"session_name": "carnivore_api", "confirm_restart_live": True}),
        ("POST", "/sessions/recreate", {"session_uuid": OWNER_UUID})]


def test_a_create_for_the_peer_machine_is_made_there(world) -> None:
    world.client.answers[("POST", "/sessions")] = (201, {"id": "ses_owner1", "working_dir": "/w"})
    world.client.answers[("GET", "/sessions")] = (200, {"tmux_session": "cloude_new"})
    reply = world.http.post("/api/v1/sessions", json={"host_key": world.key, "working_dir": "/w"})
    assert reply.status_code == 201 and reply.json()["id"] == f"remote:{world.key}:cloude_new"
    assert world.client.calls[0][:3] == ("POST", "/sessions", {"host_key": "local", "working_dir": "/w"})


def test_a_peer_caller_naming_a_remote_id_gets_409(world) -> None:
    head = {"Authorization": f"Bearer {world.peer_bearer}"}
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"}, headers=head)
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "not_local"
    also = world.http.post("/api/v1/sessions/recreate", json={"session_uuid": world.shadow_uuid}, headers=head)
    assert also.status_code == 409 and world.client.calls == []


def test_an_unauthenticated_caller_gets_401_and_nothing_is_confirmed(world) -> None:
    app.dependency_overrides.pop(require_auth, None)
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert reply.status_code == 401 and world.client.calls == []


def test_a_route_missing_from_the_table_fails_closed(world) -> None:
    world.monkeypatch.setattr(peer_forward, "_PATTERNS", [(p, r) for p, r in peer_forward._PATTERNS if r.path != "/sessions/{session_id}/name"])
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "peer_route_unsupported"
    assert world.client.calls == []


def test_a_refused_route_is_named(world) -> None:
    reply = world.http.get(f"/api/v1/sessions/{world.wire}/spectator-links")
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "peer_route_unsupported"


def test_a_spectator_link_cannot_be_minted_listed_or_revoked_for_a_peer_session(world) -> None:
    base = f"/api/v1/sessions/{world.wire}/spectator-links"
    for reply in (world.http.post(base, json={}), world.http.get(base), world.http.delete(base + "/abc")):
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "peer_route_unsupported"
    assert world.client.calls == []


def test_a_route_the_peer_is_too_old_for_is_409_capability(world) -> None:
    world.monkeypatch.setattr(peer_forward, "_PATTERNS", [(p, dataclasses.replace(r, min_minor=1)) for p, r in peer_forward._PATTERNS])
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "peer_capability_missing"
    assert world.client.calls == []


def test_a_down_or_silent_peer_is_named_not_handled_locally(world) -> None:
    world.client.answers[("PATCH", "/sessions/carnivore_api/name")] = PeerUnreachable("timeout")
    assert world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"}).status_code == 504
    world.monkeypatch.setattr(peer_links, "LINKS", FakeLinks(None))
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert reply.status_code == 503 and reply.json()["detail"]["code"] == "peer_unavailable"


def test_a_local_session_is_not_forwarded(world) -> None:
    reply = world.http.get("/api/v1/sessions/carnivore_api/note")
    assert world.client.calls == [] and reply.status_code != 409


def test_a_listing_records_the_owners_own_session_ids(world) -> None:
    raw = {"session": {"id": "ses_owner7", "working_dir": "/w", "status": "running"}, "tmux_session": "carnivore_api",
           "origin_install_id": PEER_IID, "host_key": "local", "session_uuid": OWNER_UUID, "session_row_id": 7}
    with closing(peer_auth.open_db()) as conn:
        peer = peer_hosts.get(conn, PEER_IID)
    peer_listing.reset()
    peer_listing._import(peer_auth.open_db, peer, [raw])
    assert peer_listing.owner_session_id(world.key, "carnivore_api") == "ses_owner7"
    peer_listing.reset()


def test_a_session_id_the_owner_does_not_know_is_asked_again_by_name(world) -> None:
    world.monkeypatch.setitem(peer_listing._OWNER_IDS, world.key, {"carnivore_api": "ses_gone"})
    world.client.answers[("PATCH", "/sessions/ses_gone/name")] = (404, {"detail": "no"})
    world.client.answers[("PATCH", "/sessions/carnivore_api/name")] = (200, {"renamed": True})
    reply = world.http.patch(f"/api/v1/sessions/{world.wire}/name", json={"new_name": "x"})
    assert reply.status_code == 200 and [c[1] for c in world.client.calls] == [
        "/sessions/ses_gone/name", "/sessions/carnivore_api/name"]


def test_a_session_answer_carries_the_wire_id_not_the_owners_own(world) -> None:
    world.client.answers[("GET", "/sessions")] = (200, {"session": {"id": "ses_owner1"}, "tmux_session": "carnivore_api",
                                                        "host_key": "local", "host_label": "this machine"})
    reply = world.http.get("/api/v1/sessions", params={"session_id": world.wire, "include_scrollback": "1"}).json()
    assert reply["session"]["id"] == world.wire
    assert (reply["host_key"], reply["host_label"]) == (world.key, "hosta")


def test_the_whole_ask_batch_answer_for_a_paired_computers_ask_goes_to_that_computer(world) -> None:
    body = {"questions_fingerprint": "ab" * 32, "answers": [{"option": "Blue"}, {"options": ["Cheese"], "other": "Corn"}]}
    world.monkeypatch.setattr(peer_links, "LINKS", FakeLinks(world.client, minor=3))
    world.client.answers[("POST", "/sessions/ses_owner9/dialog/answer-all")] = (200, {"count": 2, "via": "review", "questions_fingerprint": "ab" * 32})
    world.monkeypatch.setitem(peer_listing._OWNER_IDS, world.key, {"carnivore_api": "ses_owner9"})
    reply = world.http.post(f"/api/v1/sessions/{world.wire}/dialog/answer-all", json=body)
    assert reply.status_code == 200 and reply.json()["via"] == "review"
    assert world.client.calls == [("POST", "/sessions/ses_owner9/dialog/answer-all", body, None)]


def test_the_batch_answer_for_a_computer_that_lacks_the_route_is_refused_by_name_and_never_sent(world) -> None:
    body = {"questions_fingerprint": "ab" * 32, "answers": [{"option": "Blue"}]}
    world.client.answers[("POST", "/sessions/carnivore_api/dialog/answer-all")] = (404, {"detail": "Not Found"})
    reply = world.http.post(f"/api/v1/sessions/{world.wire}/dialog/answer-all", json=body)
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "peer_capability_missing"
    assert world.client.calls == []


def test_a_file_upload_into_a_paired_computers_session_goes_to_that_computer(world) -> None:
    from src.config import settings
    from src.core.federation.pairing import UPLOAD_MINOR

    world.monkeypatch.setattr(type(settings), "load_auth_config",
                              lambda self: SimpleNamespace(uploads=SimpleNamespace(max_size_mb=10, max_file_size_mb=50)))
    world.monkeypatch.setattr(peer_links, "LINKS", FakeLinks(world.client, minor=UPLOAD_MINOR))
    world.monkeypatch.setitem(peer_listing._OWNER_IDS, world.key, {"carnivore_api": "ses_owner9"})
    saved = {"path": "/w/.cloude_uploads/49759e95-note.txt", "filename": "49759e95-note.txt", "size": 5}
    world.client.answers[("POST", "/sessions/upload-file")] = (201, saved)
    reply = world.http.post("/api/v1/sessions/upload-file", params={"session_id": world.wire},
                            files={"file": ("note.txt", b"hello", "text/plain")})
    assert reply.status_code == 201 and reply.json() == saved
    method, path, json_body, timeout = world.client.calls[0]
    assert (method, path, json_body, timeout) == ("POST", "/sessions/upload-file?session_id=ses_owner9", None, peer_forward.SLOW_SECONDS)
    content, headers = world.client.raw
    assert b'filename="note.txt"' in content and b"hello" in content
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")

    old = FakeClient({})
    world.monkeypatch.setattr(peer_links, "LINKS", FakeLinks(old, minor=UPLOAD_MINOR - 1))
    refused = world.http.post("/api/v1/sessions/upload-file", params={"session_id": world.wire},
                              files={"file": ("note.txt", b"hello", "text/plain")})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "peer_capability_missing"
    assert old.calls == []
