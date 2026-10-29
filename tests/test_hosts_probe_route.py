
from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import hosts_routes
from src.api.auth import create_access_token, create_refresh_token, require_auth
from src.core.hosts import probe
from src.core.hosts import store as hosts_store
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture
from tests.test_hosts_probe import stage

API = "/api/v1/hosts"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


@pytest.fixture
def host() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def _client(tmp_path: Path, monkeypatch, host: FakeSshHost, *, owner: bool = True) -> TestClient:
    from src.config import settings

    state_dir = tmp_path / "state"
    migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    monkeypatch.setattr(hosts_routes, "probe_host", functools.partial(
        probe.probe_host, ssh_binary=host.ssh_binary, tmux_candidates=(), timeout=20.0))
    app = FastAPI()
    app.include_router(hosts_routes.router, prefix="/api/v1")
    if owner:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def _add(client: TestClient, key: str = "fake") -> None:
    with mock.patch.object(hosts_store, "generate_key", return_value=key):
        res = client.post(API, json={"label": "Fake", "ssh_target": "alex@fakehost"})
    assert res.status_code == 200, res.text


def test_a_probe_is_stored_and_answered(tmp_path, monkeypatch, host) -> None:
    client = _client(tmp_path, monkeypatch, host)
    _add(client)
    stage(host)
    res = client.post(f"{API}/fake/probe")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["probe_state"] == "ok", body["probe_detail"]
    assert (body["tmux_path"], body["tmux_version"]) == (str(host.bin_dir / "tmux"), "3.7c")
    assert body["login_shell"] == "/bin/sh" and body["login_path"].startswith(str(host.bin_dir))
    assert body["agent_paths"] == {"claude": str(host.bin_dir / "claude")}
    assert body["remote_carnivore"] == "none" and body["machine_id"]
    assert STAMP.match(body["probed_at"])
    stored = client.get(f"{API}/fake").json()
    assert {k: stored[k] for k in body if k != "session_count"} == {
        k: body[k] for k in body if k != "session_count"}


def test_a_failed_probe_is_a_stored_verdict_and_clears_old_findings(
        tmp_path, monkeypatch, host) -> None:
    client = _client(tmp_path, monkeypatch, host)
    _add(client)
    stage(host)
    assert client.post(f"{API}/fake/probe").json()["tmux_version"] == "3.7c"

    host.set("scenario", "host_key_changed")
    res = client.post(f"{API}/fake/probe")
    assert res.status_code == 200
    body = res.json()
    assert body["probe_state"] == "host_key_changed"
    assert body["probe_detail"].startswith("the host key changed since it was first trusted")
    assert body["tmux_path"] is None and body["tmux_version"] is None
    assert body["agent_paths"] is None, "not measured must read null, never an empty set"
    assert body["remote_carnivore"] == "unknown"

    host.set("scenario", "ok")
    assert client.post(f"{API}/fake/probe").json()["probe_state"] == "ok"


def test_the_probe_route_refuses_what_it_cannot_probe(tmp_path, monkeypatch, host) -> None:
    client = _client(tmp_path, monkeypatch, host)
    local = client.post(f"{API}/local/probe")
    assert local.status_code == 409 and local.json()["detail"]["code"] == "host_local_fixed"
    missing = client.post(f"{API}/nope/probe")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "host_not_found"
    assert host.calls() == [], "a refused probe contacted a host"


def test_only_an_owner_access_token_may_probe(tmp_path, monkeypatch, host) -> None:
    from src.config import settings

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {}}))
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    settings._auth_config_cache = None
    try:
        client = _client(tmp_path, monkeypatch, host, owner=False)
        _add_as = {"Authorization": f"Bearer {create_access_token()[0]}"}
        with mock.patch.object(hosts_store, "generate_key", return_value="fake"):
            assert client.post(API, json={"label": "Fake",
                                          "ssh_target": "alex@fakehost"}, headers=_add_as).status_code == 200
        refresh, _, _ = create_refresh_token()
        assert client.post(f"{API}/fake/probe").status_code == 401
        assert client.post(f"{API}/fake/probe", headers={
            "Authorization": f"Bearer {refresh}"}).status_code == 401
        assert host.calls() == []
        stage(host)
        assert client.post(f"{API}/fake/probe", headers=_add_as).json()["probe_state"] == "ok"
    finally:
        settings._auth_config_cache = None
