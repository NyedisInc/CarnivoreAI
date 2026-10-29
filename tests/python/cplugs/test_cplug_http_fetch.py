
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import socket
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import netguard, routes as host_routes, runtime, secret_store
from src.cplugs.host.egress_log import EgressLog
from src.cplugs.host.fetch_proxy import FetchRefused, PluginFetch, RateLimiter
from src.cplugs.host.fetch_transport import RawResponse
from src.cplugs.host.secret_store import SecretError, SecretStore
from src.cplugs.sdk import ManifestError
from src.cplugs.sdk.manifest import parse_manifest

TOKEN = "ghp_exampleTOKENvalue1234"  # synthetic test value, never issued
OTHER = "other_secret_value_5678"
WRITE_ENTRY = "network_hosts.write:api.example.com"
BASE_PERMS = ["network_hosts:api.example.com", "network_hosts:cdn.example.org", "lan_hosts:http://203.0.113.13:8080",
              "lan_hosts:http://nas.local:9000"]


def manifest_raw(**over):
    raw = {
        "schema": 1, "id": "netdemo", "name_key": "cplug.netdemo.name", "description_key": "cplug.netdemo.description",
        "version": "1.0.0", "icon": "list", "author": "test", "min_app_version": "1.12.20", "tier": "builtin",
        "default_enabled": False, "surfaces": {}, "settings_schema": {"version": 1, "fields": {}},
        "permissions": {"app": [*BASE_PERMS, WRITE_ENTRY]},
        "secrets": [{"name": "token", "label": "API token", "help": "from settings"},
                    {"name": "cdn", "label": "CDN key", "help": "from settings"}],
        "network_hosts": [
            {"host": "api.example.com", "reason": "reads", "methods": ["GET", "POST"], "paths": ["/repos", "/user"],
             "auth": {"secret": "token", "header": "Authorization", "scheme": "Bearer"}},
            {"host": "cdn.example.org", "reason": "assets", "auth": {"secret": "cdn", "header": "X-Key", "scheme": ""}}],
        "lan_hosts": [{"host": "http://203.0.113.13:8080", "reason": "printer"},
                      {"host": "http://nas.local:9000", "reason": "nas"}],
    }
    raw.update(over)
    return raw


class FakeKeychain:

    def __init__(self):
        self.items: Dict[tuple, str] = {}

    def read(self, service, account): return self.items.get((service, account))
    def write(self, service, account, secret): self.items[(service, account)] = secret
    def delete(self, service, account): return self.items.pop((service, account), None) is not None


class FakeTransport:

    def __init__(self):
        self.calls: List[dict] = []
        self.answers: List[RawResponse] = []

    def send(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0) if self.answers else RawResponse(200, [("Content-Type", "text/plain")], b"ok")


class Rig:

    def __init__(self, tmp_path: Path, raw=None, grants=None):
        self.m = parse_manifest(raw or manifest_raw())
        self.grants = set(grants if grants is not None else self.m.permissions)
        self.kc, self.transport = FakeKeychain(), FakeTransport()
        self.secrets = SecretStore(tmp_path, keychain=self.kc)
        self.log = EgressLog(tmp_path)
        self.dns: Dict[str, List[str]] = {"api.example.com": ["93.184.216.34"], "cdn.example.org": ["151.101.1.1"],
                                          "nas.local": ["198.51.100.17"]}
        self.resolved: List[str] = []
        self.peers: set = set()
        self.peers_complete = True
        self.own: set = set()
        self.limiter = RateLimiter()
        self.secrets.set("netdemo", self.m, "token", TOKEN)
        self.secrets.set("netdemo", self.m, "cdn", OTHER)

    def proxy(self) -> PluginFetch:
        def resolver(host, port):
            self.resolved.append(host)
            if host not in self.dns:
                raise netguard.Refused("dns_failed")
            return self.dns[host]

        return PluginFetch(self.m, "netdemo", lambda: self.grants, self.secrets, self.log, self.limiter,
                           peers=lambda: netguard.Peers(self.peers, self.peers_complete),
                           resolver=resolver, transport=self.transport, is_own=lambda ip: ip in self.own)

    def get(self, url, method="GET", **kw):
        return self.proxy().fetch_blocking(method, url, **kw)

    def refused(self, url, code, method="GET", **kw):
        with pytest.raises(FetchRefused) as info:
            self.get(url, method, **kw)
        assert info.value.code == code, info.value
        assert self.transport.calls == [], "the transport was reached"
        assert self.log.recent("netdemo", 1)[0]["outcome"] == code


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)



@pytest.mark.parametrize("change", [
    {"network_hosts": [{"host": "192.0.2.5", "reason": "x"}]},
    {"network_hosts": [{"host": "*.example.com", "reason": "x"}]},
    {"network_hosts": [{"host": "localhost", "reason": "x"}]},
    {"network_hosts": [{"host": "api.example.com", "reason": "x", "auth": {"secret": "nope", "header": "X", "scheme": ""}}]},
    {"network_hosts": [{"host": "api.example.com", "reason": "x", "auth": {"secret": "token", "header": "Host", "scheme": ""}}]},
    {"lan_hosts": [{"host": "http://127.0.0.1:80", "reason": "x"}]},
    {"lan_hosts": [{"host": "http://169.254.169.254:80", "reason": "x"}]},
    {"lan_hosts": [{"host": "http://8.8.8.8:80", "reason": "x"}]},
    {"lan_hosts": [{"host": "http://2130706433:80", "reason": "x"}]},
    {"permissions": {"app": BASE_PERMS}},
    {"permissions": {"app": [*BASE_PERMS, WRITE_ENTRY, "network_hosts:other.example.com"]}},
])
def test_a_bad_network_declaration_refuses_the_whole_manifest(change):
    with pytest.raises(ManifestError):
        parse_manifest(manifest_raw(**change))


def test_a_write_method_is_its_own_permission():
    m = parse_manifest(manifest_raw())
    assert WRITE_ENTRY in m.permissions and m.network.network_hosts[1].methods == ("GET", "HEAD")
    assert m.network.secret_hosts("token") == ("api.example.com",)



def test_a_granted_get_connects_to_the_checked_address_and_injects_the_secret(rig):
    r = rig.get("https://API.Example.com./repos/o/r?page=2", headers={
        "Accept": "application/json", "Authorization": "Bearer plugin-chosen", "Host": "evil.test", "Cookie": "a=b",
        "X-Forwarded-For": "1.2.3.4", "Proxy-Authorization": "x"})
    call = rig.transport.calls[0]
    assert (call["ip"], call["port"], call["tls"], call["host"], call["method"]) == ("93.184.216.34", 443, True, "api.example.com", "GET")
    assert call["target"] == "/repos/o/r?page=2"
    sent = {k.lower(): v for k, v in call["headers"]}
    assert sent["authorization"] == f"Bearer {TOKEN}" and sent["accept"] == "application/json"
    assert not {"host", "cookie", "x-forwarded-for", "proxy-authorization"} & set(sent)
    assert r.status == 200 and r.body == b"ok" and rig.resolved == ["api.example.com"]
    row = rig.log.recent("netdemo", 1)[0]
    assert (row["host"], row["method"], row["status"], row["outcome"]) == ("api.example.com", "GET", 200, "ok")
    assert "repos" not in str(row) and "page" not in str(row) and TOKEN not in str(row)


def test_the_response_loses_cookies_challenges_and_any_echo_of_the_secret(rig):
    rig.transport.answers.append(RawResponse(200, [("Set-Cookie", "s=1"), ("WWW-Authenticate", "Basic"), ("X-Echo", TOKEN),
                                                  ("Content-Type", "text/plain")], f"hello {TOKEN} bye".encode()))
    r = rig.get("https://api.example.com/repos/x")
    assert r.headers == {"content-type": "text/plain"} and r.body == b"hello [redacted] bye"
    assert rig.log.recent("netdemo", 1)[0]["outcome"] == "credential_echo"



def test_an_ungranted_host_scheme_port_and_userinfo_are_refused(rig):
    rig.refused("https://evil.example.net/repos", "permission_denied")
    rig.refused("http://api.example.com/repos", "scheme_refused")
    rig.refused("https://api.example.com:8443/repos", "port_refused")
    rig.refused("https://user:pw@api.example.com/repos", "userinfo_refused")
    rig.refused("ftp://api.example.com/repos", "scheme_refused")
    rig.refused("https://sub.api.example.com/repos", "permission_denied")
    rig.grants.discard("network_hosts:api.example.com")
    rig.refused("https://api.example.com/repos", "permission_denied")


@pytest.mark.parametrize("host", ["127.0.0.1", "2130706433", "0x7f.1", "0177.0.0.1", "[::1]", "[::ffff:127.0.0.1]", "198.51.100.15"])
def test_an_ip_literal_is_refused_unless_a_lan_entry_names_it(rig, host):
    rig.refused(f"https://{host}/repos", "ip_literal")


def test_a_write_needs_its_own_tick_and_the_declared_method_and_path(rig):
    rig.refused("https://api.example.com/repos/x", "method_refused", "DELETE", body=None)
    rig.refused("https://cdn.example.org/a", "method_refused", "POST", body=b"x")
    rig.grants.discard(WRITE_ENTRY)
    rig.refused("https://api.example.com/repos/x", "write_not_granted", "POST", body=b"{}")
    rig.grants.add(WRITE_ENTRY)
    assert rig.get("https://api.example.com/repos/x", "POST", body=b"{}").status == 200
    rig.transport.calls.clear()
    rig.refused("https://api.example.com/admin", "path_refused")
    rig.refused("https://api.example.com/repos/../admin", "path_refused")
    rig.refused("https://api.example.com/repos/%2e%2e/admin", "path_refused")
    rig.refused("https://api.example.com/reposX", "path_refused")


@pytest.mark.parametrize("answer", [["127.0.0.1"], ["::1"], ["169.254.169.254"], ["0.0.0.0"], ["::ffff:127.0.0.1"],
                                    ["64:ff9b::7f00:1"], ["2002:7f00:1::"], ["::127.0.0.1"], ["fd00:ec2::254"],
                                    ["93.184.216.34", "127.0.0.1"]])
def test_a_name_resolving_to_a_never_address_is_refused_even_among_public_ones(rig, answer):
    rig.dns["api.example.com"] = answer
    rig.refused("https://api.example.com/repos", "address_never")


@pytest.mark.parametrize("answer", [["192.0.2.13"], ["203.0.113.17"], ["100.101.0.77"], ["fd12::1"], ["93.184.216.34", "192.0.2.13"]])
def test_a_name_resolving_private_is_refused_without_a_lan_grant(rig, answer):
    rig.dns["api.example.com"] = answer
    rig.refused("https://api.example.com/repos", "private_address")


def test_this_computers_own_address_and_a_paired_peers_are_never_reachable(rig):
    rig.dns["api.example.com"] = ["93.184.216.34"]
    rig.own.add("93.184.216.34")
    rig.refused("https://api.example.com/repos", "address_never")
    rig.own.clear()
    rig.peers.add("93.184.216.34")
    rig.refused("https://api.example.com/repos", "address_never")
    rig.peers.clear()
    assert rig.get("https://api.example.com/repos").status == 200


def test_the_outgoing_tripwire_stops_a_detected_secret_in_the_query_header_or_body(rig):
    key = "AKIAIOSFODNN7EXAMPLE"
    rig.refused(f"https://api.example.com/repos?k={key}", "secret_in_request")
    rig.refused("https://api.example.com/repos", "secret_in_request", headers={"X-Note": key})
    rig.refused("https://api.example.com/repos", "secret_in_request", "POST", body=f"data {key}".encode())


def test_header_injection_size_rate_and_a_missing_secret_are_refused(rig):
    rig.refused("https://api.example.com/repos", "bad_header", headers={"X-A": "v\r\nInjected: 1"})
    with pytest.raises(FetchRefused) as big:
        rig.get("https://api.example.com/repos", "POST", body=b"x" * (256 * 1024 + 1))
    assert big.value.code == "request_too_large" and rig.transport.calls == []
    rig.kc.items.clear()
    rig.refused("https://api.example.com/repos", "secret_missing")
    rig.secrets.set("netdemo", rig.m, "cdn", OTHER)
    rig.limiter = RateLimiter(per_minute=2)
    rig.get("https://cdn.example.org/a")
    rig.get("https://cdn.example.org/a")
    rig.transport.calls.clear()
    rig.refused("https://cdn.example.org/a", "rate_limited")



def test_a_granted_lan_entry_reaches_a_private_address_over_http_only_there(rig):
    rig.dns["203.0.113.13"] = ["203.0.113.13"]
    assert rig.get("http://203.0.113.13:8080/status").status == 200
    call = rig.transport.calls[0]
    assert (call["ip"], call["port"], call["tls"], call["host"]) == ("203.0.113.13", 8080, False, "203.0.113.13")
    assert "authorization" not in {k.lower() for k, _ in call["headers"]}
    assert rig.get("http://nas.local:9000/x").status == 200 and rig.transport.calls[1]["ip"] == "198.51.100.17"
    rig.transport.calls.clear()
    rig.refused("http://203.0.113.13:9999/status", "ip_literal")
    rig.refused("http://192.0.2.18:8080/status", "ip_literal")


def test_lan_never_reaches_this_computer_a_peer_or_a_public_answer_and_needs_its_tick(rig):
    rig.dns["203.0.113.13"] = ["203.0.113.13"]
    rig.own.add("203.0.113.13")
    rig.refused("http://203.0.113.13:8080/status", "address_never")
    rig.own.clear()
    rig.peers.add("198.51.100.17")
    rig.refused("http://nas.local:9000/x", "address_never")
    rig.peers.clear()
    rig.dns["nas.local"] = ["8.8.8.8"]
    rig.refused("http://nas.local:9000/x", "address_not_private")
    rig.dns["nas.local"] = ["127.0.0.1"]
    rig.refused("http://nas.local:9000/x", "address_never")
    rig.dns["nas.local"] = ["198.51.100.17"]
    rig.grants.discard("lan_hosts:http://nas.local:9000")
    rig.refused("http://nas.local:9000/x", "scheme_refused")



def redirect(to):
    return RawResponse(302, [("Location", to)], b"")


def test_every_redirect_hop_is_checked_again_and_credentials_never_cross_hosts(rig):
    rig.transport.answers.append(redirect("https://cdn.example.org/asset"))
    r = rig.get("https://api.example.com/repos/x", headers={"Accept": "a/b", "X-Mine": "1"})
    first, second = rig.transport.calls
    assert {k.lower() for k, _ in first["headers"]} >= {"authorization", "x-mine"}
    sent = {k.lower(): v for k, v in second["headers"]}
    assert second["host"] == "cdn.example.org" and sent["x-key"] == OTHER
    assert "authorization" not in sent and "x-mine" not in sent and sent["accept"] == "a/b"
    assert TOKEN not in str(second) and r.status == 200
    assert [row["host"] for row in rig.log.recent("netdemo", 2)] == ["cdn.example.org", "api.example.com"]


def test_a_redirect_to_an_ungranted_host_a_private_resolution_or_too_many_hops_stops(rig):
    rig.transport.answers.append(redirect("https://evil.example.net/x"))
    with pytest.raises(FetchRefused) as hop:
        rig.get("https://api.example.com/repos/x")
    assert hop.value.code == "permission_denied" and len(rig.transport.calls) == 1
    rig.transport.calls.clear()
    rig.transport.answers.append(redirect("http://127.0.0.1/x"))
    with pytest.raises(FetchRefused) as lit:
        rig.get("https://api.example.com/repos/x")
    assert lit.value.code == "ip_literal" and len(rig.transport.calls) == 1
    rig.transport.calls.clear()
    rig.transport.answers.append(redirect("https://cdn.example.org/x"))
    rig.dns["cdn.example.org"] = ["198.51.100.16"]
    with pytest.raises(FetchRefused) as rebind:
        rig.get("https://api.example.com/repos/x")
    assert rebind.value.code == "private_address" and len(rig.transport.calls) == 1
    rig.transport.calls.clear()
    rig.dns["cdn.example.org"] = ["151.101.1.1"]
    rig.transport.answers.extend([redirect("https://cdn.example.org/a")] * 4)
    with pytest.raises(FetchRefused) as many:
        rig.get("https://cdn.example.org/a")
    assert many.value.code == "too_many_redirects" and len(rig.transport.calls) == 4



def test_a_secret_is_sent_only_to_the_host_it_was_entered_for(rig, tmp_path):
    assert rig.secrets.value_for("netdemo", rig.m, "token", "api.example.com") == TOKEN
    assert rig.secrets.value_for("netdemo", rig.m, "token", "cdn.example.org") is None
    moved = manifest_raw()
    moved["network_hosts"][0]["auth"] = None
    moved["network_hosts"][1]["auth"] = {"secret": "token", "header": "X-Key", "scheme": ""}
    new = parse_manifest(moved)
    assert rig.secrets.value_for("netdemo", new, "token", "cdn.example.org") is None
    assert rig.secrets.status("netdemo", new, "token") == {"secret_present": False, "needs_reentry": True}
    rig.secrets.set("netdemo", new, "token", "fresh_value_1")
    assert rig.secrets.value_for("netdemo", new, "token", "cdn.example.org") == "fresh_value_1"
    assert rig.secrets.value_for("netdemo", new, "token", "api.example.com") is None


def test_secret_entry_refuses_an_undeclared_name_an_unbound_name_and_an_unsafe_value(rig):
    for name, value, code in (("nope", "abc", "secret_unknown"), ("token", "has space", "secret_invalid")):
        with pytest.raises(SecretError) as info:
            rig.secrets.set("netdemo", rig.m, name, value)
        assert info.value.code == code
    unbound = manifest_raw()
    unbound["network_hosts"][0]["auth"] = None
    with pytest.raises(SecretError) as info:
        rig.secrets.set("netdemo", parse_manifest(unbound), "token", "abc")
    assert info.value.code == "secret_unbound"
    assert rig.secrets.purge("netdemo") == 2 and rig.kc.items == {}


def test_the_secret_and_egress_routes_never_return_a_value(tmp_path, monkeypatch):
    m = parse_manifest(manifest_raw())
    kc = FakeKeychain()
    monkeypatch.setattr(secret_store, "_Login", lambda: kc)
    monkeypatch.setattr(runtime, "find", lambda cid: SimpleNamespace(manifest=m) if cid == "netdemo" else None)
    app = FastAPI()
    runtime.install(app, tmp_path)
    app.include_router(host_routes.router, prefix="/api/v1")
    url = "/api/v1/cplugs/netdemo/secrets/token"
    with TestClient(app) as anonymous:
        for call in (anonymous.get(url), anonymous.put(url, json={"value": "x"}), anonymous.delete(url),
                     anonymous.get("/api/v1/cplugs/netdemo/egress")):
            assert call.status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as c:
        assert c.get(url).json() == {"secret_present": False, "needs_reentry": False}
        put = c.put(url, json={"value": TOKEN})
        assert put.status_code == 200 and put.json() == {"secret_present": True, "needs_reentry": False}
        assert TOKEN not in put.text and TOKEN not in c.get(url).text
        assert c.put(url, json={"value": "bad value"}).json()["detail"]["code"] == "secret_invalid"
        assert c.get("/api/v1/cplugs/netdemo/secrets/zzz").status_code == 404
        EgressLog(tmp_path).record("netdemo", host="api.example.com", method="GET", permission="p", status=200,
                                   bytes_out=0, bytes_in=2, ms=3, outcome="ok")
        assert c.get("/api/v1/cplugs/netdemo/egress").json()["rows"][0]["host"] == "api.example.com"
        assert c.delete(url).json() == {"secret_present": False, "needs_reentry": False} and kc.items == {}



def test_a_server_trickling_bytes_is_cut_at_the_deadline():
    from src.cplugs.host.fetch_transport import StdlibTransport

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def serve():
        c, _ = srv.accept()
        c.recv(65536)
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
        while not stop.is_set():
            try:
                c.sendall(b"x")
            except OSError:
                break
            time.sleep(0.2)

    threading.Thread(target=serve, daemon=True).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            StdlibTransport().send(ip="127.0.0.1", port=srv.getsockname()[1], tls=False, host="lan.local", method="GET",
                                   target="/", headers=[], body=None, deadline=time.monotonic() + 1.0, max_bytes=2 << 20)
    finally:
        stop.set()
        srv.close()
    assert time.monotonic() - t0 < 4


def test_a_revoked_tick_bites_on_the_next_fetch_of_a_live_proxy(rig):
    proxy = rig.proxy()
    assert proxy.fetch_blocking("GET", "https://api.example.com/repos").status == 200
    rig.grants.discard("network_hosts:api.example.com")
    n = len(rig.transport.calls)
    with pytest.raises(FetchRefused) as info:
        proxy.fetch_blocking("GET", "https://api.example.com/repos")
    assert info.value.code == "permission_denied" and len(rig.transport.calls) == n


def test_the_host_reads_grants_and_enabled_live(tmp_path):
    from src.cplugs.host import state as owner_state

    m = parse_manifest(manifest_raw())
    host = runtime.Host(tmp_path)
    owner_state.update(tmp_path, m, None, lambda st: st.__class__(**{**st.__dict__, "enabled": True, "grants": ("network_hosts:api.example.com",)}))
    assert host._live_grants(m) == {"network_hosts:api.example.com"}
    owner_state.update(tmp_path, m, None, lambda st: st.__class__(**{**st.__dict__, "grants": ()}))
    assert host._live_grants(m) == frozenset()


def test_lan_routes_fail_closed_when_the_peer_list_may_be_incomplete(rig):
    rig.dns["203.0.113.13"] = ["203.0.113.13"]
    rig.peers_complete = False
    rig.refused("http://nas.local:9000/x", "peers_unknown")
    rig.refused("http://203.0.113.13:8080/status", "peers_unknown")
    assert rig.get("https://api.example.com/repos").status == 200
    rig.peers_complete = True
    assert rig.get("http://nas.local:9000/x").status == 200


def _fake_peer_db(monkeypatch, targets, raises=None):
    import sqlite3
    from contextlib import closing as _c  # noqa: F401
    from src.api import peer_auth
    from src.core.federation import peer_hosts

    def open_db():
        if raises:
            raise raises
        return sqlite3.connect(":memory:")

    monkeypatch.setattr(peer_auth, "open_db", open_db)
    monkeypatch.setattr(peer_hosts, "list_peers", lambda conn: [SimpleNamespace(ssh_target=t) for t in targets])
    netguard._peer_cache.clear()


def test_peer_addresses_use_the_real_host_of_an_alias_and_fail_closed(monkeypatch):
    import sqlite3

    _fake_peer_db(monkeypatch, ["studio"])
    dns = {"studio": [], "100.101.0.77": ["100.101.0.77"]}

    def resolver(host, port):
        if not dns.get(host):
            raise netguard.Refused("dns_failed")
        return dns[host]

    got = netguard.peer_addresses(resolver, lambda t: "100.101.0.77", lambda: 0.0)
    assert got.addresses == {"100.101.0.77"} and got.complete
    netguard._peer_cache.clear()
    def no_ssh(t):
        raise OSError("no ssh")
    assert netguard.peer_addresses(resolver, no_ssh, lambda: 0.0).complete is False
    netguard._peer_cache.clear()
    _fake_peer_db(monkeypatch, ["studio"], raises=sqlite3.OperationalError("locked"))
    assert netguard.peer_addresses(resolver, lambda t: "100.101.0.77", lambda: 0.0) == netguard.Peers(set(), False)
    netguard._peer_cache.clear()
