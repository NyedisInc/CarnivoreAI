
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from src.api import host_guard
from src.api.host_guard import (
    ALLOWED_HOSTS_KEY,
    UNTRUSTED_CLOSE_CODE,
    HostGuardMiddleware,
    HostPolicy,
    split_host_port,
)

GOOD_HOSTS = [
    "127.0.0.1:8000",
    "[::1]:8000",
    "198.51.100.18:8000",
    "100.101.0.77:8000",
    "0.0.0.0:8000",
    "localhost:8000",
    "localhost",
    "app.localhost:8000",
    "LOCALHOST.:8000",
]

BAD_HOSTS = [
    "evil.example",
    "evil.example:8000",
    "127.0.0.1.evil.example",
    "localhost.evil.example",
    "ts.net.evil.example",
    "ts.net",
    "[::1",
    "127.0.0.1:notaport",
    "127.0.0.1:0",
    "",
]


@pytest.fixture
def policy() -> HostPolicy:
    return HostPolicy("*.ts.net, hosta")


@pytest.mark.parametrize("value,expected", [
    ("203.0.113.11:8000", ("203.0.113.11", 8000)),
    ("[::1]:8000", ("::1", 8000)),
    ("[fe80::1]", ("fe80::1", None)),
    ("Hosta.Local.", ("hosta.local", None)),
    ("::1", ("::1", None)),
    ("host:", None),
    ("[::1]x", None),
    ("host:70000", None),
])
def test_split_host_port(value, expected):
    assert split_host_port(value) == expected


@pytest.mark.parametrize("host", GOOD_HOSTS)
def test_good_hosts_trusted(policy, host):
    assert policy.host_trusted(host) is True


@pytest.mark.parametrize("host", BAD_HOSTS)
def test_bad_hosts_refused(policy, host):
    assert policy.host_trusted(host) is False


def test_missing_host_refused(policy):
    assert policy.host_trusted(None) is False


def test_machine_names_trusted(policy):
    name = socket.gethostname().lower().rstrip(".")
    bare = name[:-6] if name.endswith(".local") else name
    assert policy.host_trusted(f"{bare}:8000")
    assert policy.host_trusted(f"{bare}.local:8000")


def test_local_hostname_from_scutil_trusted(monkeypatch):
    monkeypatch.setattr(host_guard.sys, "platform", "darwin")
    monkeypatch.setattr(
        host_guard.subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout="Example-MacBook\n"),
    )
    assert HostPolicy(None).host_trusted("example-macbook.local:8000")


def test_dotted_hostname_short_label_trusted(monkeypatch):
    monkeypatch.setattr(host_guard.socket, "gethostname", lambda: "hostb.example.test")
    monkeypatch.setattr(host_guard.sys, "platform", "linux")
    names = host_guard.machine_names()
    assert {"hostb", "hostb.local"} <= names
    policy = HostPolicy(None)
    assert policy.host_trusted("hostb:8000")
    assert not policy.host_trusted("hostb.example.net:8000")


def test_configured_names_are_additive(policy):
    assert policy.host_trusted("host.example.ts.net")
    assert policy.host_trusted("hosta:8000")
    assert policy.host_trusted("localhost:8000")
    assert policy.host_trusted("192.0.2.21:8000")
    assert not HostPolicy(None).host_trusted("host.example.ts.net")


def test_wildcard_disables_check_and_logs():
    with capture_logs() as logs:
        p = HostPolicy("*")
    assert p.host_trusted("evil.example")
    assert any(e["event"] == "host_check_disabled" for e in logs)


def test_malformed_entry_ignored_and_logged():
    with capture_logs() as logs:
        p = HostPolicy("hosta:8000, http://x/, *bad, ok.example")
    assert p.host_trusted("ok.example")
    assert not p.host_trusted("hosta")
    ignored = [e["entry"] for e in logs if e["event"] == "allowed_hosts_entry_ignored"]
    assert ignored == ["hosta:8000", "http://x/", "*bad"]


def test_settings_reads_the_prefixed_key(monkeypatch):
    from src.config.settings import Settings
    monkeypatch.setenv("CLOUDE_ALLOWED_HOSTS", "hosta")
    monkeypatch.delenv("CARNIVORE_ALLOWED_HOSTS", raising=False)
    assert Settings(_env_file=None, default_working_dir="/tmp").allowed_hosts_extra == "hosta"
    assert ALLOWED_HOSTS_KEY == "CARNIVORE_ALLOWED_HOSTS"




@pytest.fixture
def real_app():
    from src.main import app
    return app


def test_middleware_registered_on_real_app(real_app):
    assert HostGuardMiddleware in [m.cls for m in real_app.user_middleware]


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "localhost.evil.example"])
def test_real_app_refuses_foreign_host(real_app, host):
    client = TestClient(real_app)
    with capture_logs() as logs:
        r = client.get("/health", headers={"host": host})
    assert r.status_code == 400
    assert ALLOWED_HOSTS_KEY in r.text
    assert any(e["event"] == "host_rejected" and e["host"] == host for e in logs)


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "[::1]:8000", "198.51.100.18:8000", "localhost:8000"])
def test_real_app_answers_trusted_host(real_app, host):
    r = TestClient(real_app).get("/health", headers={"host": host})
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/ws/terminal", "/ws/events"])
def test_real_app_socket_refuses_foreign_host(real_app, path):
    client = TestClient(real_app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path, headers={"host": "evil.example"}) as ws:
            ws.receive_text()
    assert exc.value.code == UNTRUSTED_CLOSE_CODE


@pytest.mark.parametrize("path", ["/ws/terminal", "/ws/events"])
def test_real_app_socket_trusted_host_reaches_auth(real_app, path):
    client = TestClient(real_app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path, headers={"host": "127.0.0.1:8000"}) as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_enrollment_takeover_path_closed(real_app, tmp_path, monkeypatch):
    import json

    import src.api.auth as auth_mod
    import src.api.enrollment_routes as enrollment_routes
    from src.config import settings

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": {}}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(settings, "totp_secret", "JBSWY3DPEHPK3PXP")
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret-not-a-real-one-32b")
    monkeypatch.setattr(enrollment_routes, "env_file_path", lambda: tmp_path / "absent.env")
    settings.drop_auth_config_cache()
    auth_mod.limiter.reset()
    try:
        client = TestClient(
            real_app, base_url=f"http://127.0.0.1:{settings.port}", client=("127.0.0.1", 50000)
        )
        refused = client.get("/api/v1/auth/enrollment", headers={"host": "attacker-rebind.example:8000"})
        assert refused.status_code == 400
        assert "JBSWY3DPEHPK3PXP" not in refused.text
        served = client.get("/api/v1/auth/enrollment", headers={"host": f"127.0.0.1:{settings.port}"})
        assert served.status_code == 200
        assert served.json()["secret"] == "JBSWY3DPEHPK3PXP"
    finally:
        settings.drop_auth_config_cache()
        auth_mod.limiter.reset()
