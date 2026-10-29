
from __future__ import annotations

import json
import os
import re
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import create_access_token, create_refresh_token, require_auth
from src.api.hosts_routes import router as hosts_router
from src.core.db import connect
from src.core.hosts import store
from src.core.hosts.ddl import REVERSAL_SQL_V40

FIXTURE = Path(__file__).parent / "fixtures" / "hosts_api.json"
API = "/api/v1/hosts"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _client(tmp_path: Path, monkeypatch, *, owner_override: bool = True):
    from src.config import settings

    state_dir = tmp_path / "state"
    db_path = migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    app = FastAPI()
    app.include_router(hosts_router, prefix="/api/v1")
    if owner_override:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app), db_path


def _session_on(db_path: Path, host_key: str) -> None:
    with closing(connect(db_path, create=False)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
            "origin, lifecycle, host_key, created_at, updated_at) VALUES (?, 'carnivore-remote', "
            "'carnivore_x', 1790000000, 'created', 'running', ?, 'now', 'now')",
            (f"on-{host_key}", host_key))


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, str) and STAMP.match(value):
        return "<timestamp>"
    return value


def _mask(value: Any, replacements: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _mask(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, replacements) for v in value]
    if isinstance(value, str):
        out = value
        for real, placeholder in replacements.items():
            out = out.replace(real, placeholder)
        return out
    return value


def _examples(client, db_path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    replacements: Dict[str, str] = {}

    def call(title: str, method: str, path: str, body: Any = None):
        res = client.request(method, path, json=body)
        out.append({"title": title, "method": method, "path": path, "request": body,
                    "status": res.status_code, "response": res.json()})
        return res

    call("list, fresh install: this machine only", "GET", API)
    res = call("add by ssh alias", "POST", API, {"label": "Studio", "ssh_target": "studio"})
    alias_key = res.json()["key"]
    replacements[alias_key] = "<host-key-1>"
    res = call("add with user@host, port and socket", "POST", API,
         {"label": "Lab", "ssh_target": "alex@studio.local",
          "ssh_port": 2222, "socket": "carnivore-lab"})
    studio_key = res.json()["key"]
    replacements[studio_key] = "<host-key-2>"
    call("add, 422 key is not a field the caller may set", "POST", API,
         {"key": "evil", "label": "x", "ssh_target": "studio"})
    call("add, 400 a leading '-' would be an ssh option", "POST", API,
         {"label": "x", "ssh_target": "-oProxyCommand=touch /tmp/pwned"})
    call("add, 400 a host part starting '-'", "POST", API,
         {"label": "x", "ssh_target": "alex@-oProxyCommand=x"})
    call("add, 400 a shell metacharacter", "POST", API,
         {"label": "x", "ssh_target": "studio;id"})
    call("add, 400 port out of range", "POST", API,
         {"label": "x", "ssh_target": "studio", "ssh_port": 70000})
    call("add, 400 the product's own socket (D1)", "POST", API,
         {"label": "x", "ssh_target": "studio", "socket": "carnivore"})
    call("add, 400 label invalid", "POST", API, {"label": "  ", "ssh_target": "studio"})
    call("get this machine", "GET", f"{API}/local")
    call("get one", "GET", f"{API}/{alias_key}")
    call("get, 404", "GET", f"{API}/nope")
    call("edit label and enabled", "PATCH", f"{API}/{alias_key}", {"label": "Studio (studio)", "enabled": False})
    call("edit, 409 this machine is fixed", "PATCH", f"{API}/local", {"label": "mine"})
    _session_on(db_path, alias_key)
    call("edit socket, 409 while sessions run there", "PATCH", f"{API}/{alias_key}",
         {"socket": "other-socket"})
    call("delete, 409 while sessions rows name it", "DELETE", f"{API}/{alias_key}")
    call("delete (nothing on that machine is touched)", "DELETE", f"{API}/{studio_key}")
    call("delete, 409 this machine", "DELETE", f"{API}/local")
    call("delete, 404", "DELETE", f"{API}/{studio_key}")
    call("list", "GET", API)
    with closing(connect(db_path, create=False)) as conn:
        for statement in REVERSAL_SQL_V40:
            conn.execute(statement)
    call("list, table unreadable: 200 unavailable, never an empty ok", "GET", API)
    call("add, 503 datastore unavailable", "POST", API,
         {"label": "x", "ssh_target": "studio"})
    return [_normalise(_mask(entry, replacements)) for entry in out]


def test_the_fixture_matches_the_live_routes(tmp_path, monkeypatch):
    client, db_path = _client(tmp_path, monkeypatch)
    examples = _examples(client, db_path)
    document = {
        "description": (
            "Request and response examples for every /api/v1/hosts route (issue #162, "
            "slice S1). <timestamp> stands for a generated value. Regenerated and checked "
            "by tests/test_hosts_routes.py. Model: docs/remote-hosts.md."),
        "examples": examples,
    }
    if os.environ.get("HOSTS_FIXTURE_WRITE") == "1":
        FIXTURE.write_text(json.dumps(document, indent=2) + "\n")
    stored = json.loads(FIXTURE.read_text())
    assert len(stored["examples"]) == len(examples) >= 20
    for want, got in zip(stored["examples"], examples):
        assert got == want, want["title"]
    assert {e["status"] for e in examples} >= {200, 400, 404, 409, 503}


def test_unknown_fields_are_refused_so_a_target_is_never_silently_kept(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    created = client.post(API, json={"label": "T", "ssh_target": "studio"})
    assert created.status_code == 200
    alias_key = created.json()["key"]
    assert client.post(API, json={"key": "z", "label": "Z", "ssh_target": "z"}).status_code == 422
    assert client.patch(f"{API}/{alias_key}", json={"ssh_target": "evil"}).status_code == 422
    assert client.post(API, json={"label": "X", "ssh_target": "x",
                                  "command": "id"}).status_code == 422
    assert client.post(API, json={"label": "Y", "ssh_target": "y",
                                  "ssh_port": "22"}).status_code == 422
    assert client.patch(f"{API}/{alias_key}", json={"enabled": "no"}).status_code == 422
    assert client.get(f"{API}/{alias_key}").json()["ssh_target"] == "studio"


def test_only_an_owner_access_token_reaches_host_mutation(tmp_path, monkeypatch):
    from src.config import settings

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {}}))
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    settings._auth_config_cache = None
    try:
        client, _ = _client(tmp_path, monkeypatch, owner_override=False)
        body = {"label": "Studio", "ssh_target": "studio"}
        refresh, _, _ = create_refresh_token()
        access, _ = create_access_token()
        for method, path in (("GET", API), ("POST", API), ("GET", f"{API}/local"),
                             ("PATCH", f"{API}/local"), ("DELETE", f"{API}/local")):
            json_body = body if method == "POST" else ({} if method == "PATCH" else None)
            assert client.request(method, path, json=json_body).status_code == 401, (method, path)
            assert client.request(method, path, json=json_body, headers={
                "Authorization": f"Bearer {refresh}"}).status_code == 401, (method, path)
        created = client.post(API, json=body, headers={"Authorization": f"Bearer {access}"})
        assert created.status_code == 200
        assert re.fullmatch(r"[0-9a-f]{32}", created.json()["key"])
    finally:
        settings._auth_config_cache = None



BAD_TARGETS = [
    "-oProxyCommand=touch /tmp/pwned", "-p22", "alex@-oProxyCommand=x", "studio;id", "studio id",
    "$(id)", "`id`", "studio|cat", "studio&", "a@b@c", "", ".studio", "studio\n", "alex@", "@studio",
    "stu:dio", "studio/x", "~studio", "studio%h", "x" * 255, 22, None,
]
GOOD_TARGETS = ["studio", "alex@studio", "studio.local", "100.64.0.1", "my_host-1", "u+x@h",
                "_svc@box", "a" * 254]


@pytest.mark.parametrize("target", BAD_TARGETS)
def test_a_target_that_could_be_an_option_or_carry_a_command_is_refused(target):
    with pytest.raises(store.HostInvalid) as caught:
        store.validate_ssh_target(target)
    assert caught.value.code == "host_target_invalid"


@pytest.mark.parametrize("target", GOOD_TARGETS)
def test_an_alias_or_user_at_host_is_accepted_as_is(target):
    assert store.validate_ssh_target(target) == target


@pytest.mark.parametrize("key,code", [
    ("Studio", "host_key_invalid"), ("-studio", "host_key_invalid"), ("stu_dio", "host_key_invalid"),
    ("", "host_key_invalid"), ("a" * 33, "host_key_invalid"), ("studio\n", "host_key_invalid"),
    ("local", "host_key_reserved"),
])
def test_a_key_is_a_slug_and_local_is_reserved(key, code):
    with pytest.raises(store.HostInvalid) as caught:
        store.validate_key(key)
    assert caught.value.code == code


@pytest.mark.parametrize("socket,code", [
    ("carnivore", "host_socket_reserved"), ("cloude", "host_socket_reserved"),
    ("-L", "host_socket_invalid"), ("a/b", "host_socket_invalid"), ("", "host_socket_invalid"),
    ("x" * 65, "host_socket_invalid"), ("a b", "host_socket_invalid"),
])
def test_a_socket_is_a_plain_name_and_never_the_products_own(socket, code):
    with pytest.raises(store.HostInvalid) as caught:
        store.validate_socket(socket)
    assert caught.value.code == code


@pytest.mark.parametrize("port", [0, -1, 65536, True, "22"])
def test_a_port_is_an_integer_in_range(port):
    with pytest.raises(store.HostInvalid):
        store.validate_ssh_port(port)


def test_the_store_round_trip_and_its_refusals(tmp_path):
    db_path = migrated(tmp_path / "state")
    with closing(connect(db_path, create=False)) as conn:
        made = store.create_host(conn, label=" Studio ", ssh_target="alex@studio")
        assert (made.label, made.socket, made.ssh_port, made.enabled, made.probe_state) == (
            "Studio", "carnivore-remote", None, True, "never")
        assert re.fullmatch(r"[0-9a-f]{32}", made.key)
        _session_on(db_path, made.key)
        assert [h.key for h in store.list_hosts(conn)] == ["local", made.key]
        assert store.session_counts(conn) == {made.key: 1}
        with pytest.raises(store.HostLocalFixed):
            store.update_host(conn, "local", label="mine")
        with pytest.raises(store.HostLocalFixed):
            store.delete_host(conn, "local")
        with pytest.raises(store.HostInUse):
            store.delete_host(conn, made.key)
        with pytest.raises(store.HostInUse):
            store.update_host(conn, made.key, socket="elsewhere")
        assert store.update_host(conn, made.key, label="T2", enabled=False).enabled is False
        spare = store.create_host(conn, label="Spare", ssh_target="spare")
        assert spare.key != made.key
        store.delete_host(conn, spare.key)
        with pytest.raises(store.HostNotFound):
            store.get_host(conn, spare.key)


def test_a_paired_computer_is_pickable_only_while_connected_and_allowed_to_host(tmp_path, monkeypatch):
    from src.core.federation import peer_hosts
    from src.core.pack.machines import runtime

    client, db_path = _client(tmp_path, monkeypatch)
    allowed = {"iid-up": True, "iid-refuses": False, "iid-down": True}
    monkeypatch.setattr(runtime, "peer_restriction", lambda iid, name: allowed[iid] if name == "may_host_agents" else None)
    with closing(connect(db_path, create=False)) as conn:
        for iid in allowed:
            peer_hosts.upsert(conn, install_id=iid, label=iid, grant_id="g", fid="f", initiator=True)
        peer_hosts.set_state(conn, "iid-up", "connected")
        peer_hosts.set_state(conn, "iid-refuses", "connected")
    rows = {h["label"]: h for h in client.get(API).json()["hosts"]}
    assert (rows["iid-up"]["enabled"], rows["iid-up"]["probe_state"]) == (True, "ok")
    assert (rows["iid-refuses"]["enabled"], rows["iid-refuses"]["probe_detail"]) == (False, "peer_refuses_hosting")
    assert (rows["iid-down"]["enabled"], rows["iid-down"]["probe_detail"]) == (False, "peer_not_connected")
    with closing(connect(db_path, create=False)) as conn:
        assert conn.execute("SELECT enabled FROM hosts WHERE kind = 'peer' AND label = 'iid-up'").fetchone()[0] == 0
