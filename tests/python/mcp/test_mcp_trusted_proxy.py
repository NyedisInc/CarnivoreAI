
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api import mcp_admin_routes
from src.api.auth import require_auth
from src.config.mcp import McpConfig
from src.core import config_writer
from src.core.mcp import token_store, trusted_proxy
from src.main import app
from tests.python.mcp.test_mcp_endpoint import _hdr, _rpc, env  # noqa: F401

PROXY = "203.0.113.11"


def _cfg_settings(cfg: McpConfig) -> SimpleNamespace:
    return SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg))


@pytest.fixture
def proxied(env, monkeypatch, tmp_path):  # noqa: F811
    _client, mgr, cfg = env
    cfg.trusted_proxy_hosts = [PROXY]
    monkeypatch.setattr(trusted_proxy, "settings", _cfg_settings(cfg))
    store = token_store.TokenStore(tmp_path)
    monkeypatch.setattr(token_store, "get_store", lambda: store)
    _row, secret = store.mint("phone", "read")

    def client_for(host: str) -> TestClient:
        return TestClient(app, client=(host, 40000), raise_server_exceptions=False)

    return client_for, mgr, cfg, secret


def _owner(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}", "X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"}


def test_proxy_host_with_owner_token_is_accepted(proxied) -> None:
    client_for, _mgr, _cfg, secret = proxied
    r = client_for(PROXY).post("/mcp", json=_rpc("ping"), headers=_owner(secret))
    assert r.status_code == 200, r.text
    mapped = client_for(f"::ffff:{PROXY}").post("/mcp", json=_rpc("ping"), headers=_owner(secret))
    assert mapped.status_code == 200


def test_proxy_host_with_pane_token_is_refused(proxied) -> None:
    client_for, mgr, _cfg, _secret = proxied
    assert client_for("127.0.0.1").post("/mcp", json=_rpc("ping"), headers=_hdr(mgr)).status_code == 200
    r = client_for(PROXY).post("/mcp", json=_rpc("ping"), headers=_hdr(mgr))
    assert r.status_code == 403


def test_unlisted_remote_host_with_owner_token_is_refused(proxied) -> None:
    client_for, _mgr, _cfg, secret = proxied
    for host in ("203.0.113.12", "192.168.1.9", "::ffff:203.0.113.12"):
        assert client_for(host).post("/mcp", json=_rpc("ping"), headers=_owner(secret)).status_code == 403
    spoof = {"Authorization": f"Bearer {secret}", "X-Forwarded-For": PROXY}
    assert client_for("203.0.113.12").post("/mcp", json=_rpc("ping"), headers=spoof).status_code == 403


def test_proxy_host_with_origin_is_refused(proxied) -> None:
    client_for, _mgr, _cfg, secret = proxied
    r = client_for(PROXY).post("/mcp", json=_rpc("ping"), headers={**_owner(secret), "Origin": "https://claude.ai"})
    assert r.status_code == 403


def test_proxy_host_over_the_phone_link_is_refused(proxied) -> None:
    client_for, _mgr, _cfg, secret = proxied

    async def tag_link(scope, receive, send):
        scope = {**scope, "via_link": True}
        await app(scope, receive, send)

    linked = TestClient(tag_link, client=(PROXY, 40000), raise_server_exceptions=False)
    assert linked.post("/mcp", json=_rpc("ping"), headers=_owner(secret)).status_code == 403


def test_empty_list_keeps_the_loopback_only_gate(proxied) -> None:
    client_for, _mgr, cfg, secret = proxied
    cfg.trusted_proxy_hosts = []
    assert client_for(PROXY).post("/mcp", json=_rpc("ping"), headers=_owner(secret)).status_code == 403
    cfg.trusted_proxy_hosts = ["203.0.113.0/24", "qnap-home", "0.0.0.0"]
    assert client_for(PROXY).post("/mcp", json=_rpc("ping"), headers=_owner(secret)).status_code == 403
    assert McpConfig().trusted_proxy_hosts == []


def test_the_admin_route_validates_and_writes_through_the_config_writer(env, monkeypatch, tmp_path) -> None:  # noqa: F811
    client, mgr, _cfg = env
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"mcp": {"channels": true}}')

    def live() -> SimpleNamespace:
        return SimpleNamespace(mcp=McpConfig(**json.loads(cfg_file.read_text())["mcp"]))

    monkeypatch.setattr(mcp_admin_routes, "settings", SimpleNamespace(
        auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None, port=8123, load_auth_config=live))
    monkeypatch.setattr(trusted_proxy, "settings", SimpleNamespace(load_auth_config=live))
    commits: list = []
    real_commit = config_writer.commit
    monkeypatch.setattr(config_writer, "commit", lambda path, mutate: commits.append(path) or real_commit(path, mutate))
    body = {"hosts": [PROXY]}
    assert client.put("/api/v1/mcp-admin/trusted-proxies", json=body, headers=_hdr(mgr)).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        for bad in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "0.0.0.0", "::", "224.0.0.1", "203.0.113.0/24", "qnap-home"):
            r = client.put("/api/v1/mcp-admin/trusted-proxies", json={"hosts": [bad]})
            assert r.status_code == 422, bad
        r = client.put("/api/v1/mcp-admin/trusted-proxies", json={"hosts": [f" {PROXY} ", f"::ffff:{PROXY}"]})
        assert r.status_code == 200 and r.json() == {"hosts": [PROXY]}
        assert client.get("/api/v1/mcp-admin").json()["trusted_proxy_hosts"] == [PROXY]
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert json.loads(cfg_file.read_text())["mcp"] == {"channels": True, "trusted_proxy_hosts": [PROXY]}
    assert len(commits) == 1
