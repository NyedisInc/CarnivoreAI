
from __future__ import annotations

import base64
import logging

import httpcore
import pytest
import structlog

from src.core.notifications import http as G
from src.core.notifications.http import (
    GuardBlocked, GuardLocalPolicy, GuardNetworkError, GuardTimeout, HostPolicy, guarded_request,
)

pytestmark = pytest.mark.asyncio

POLICY = HostPolicy(exact=("hooks.example.com",), suffixes=(".logic.azure.com",))
URL = "https://hooks.example.com/services/T000/B000/SECRETPATHTOKEN?sig=SECRETQUERY"


def _http(status=200, body=b"ok", extra=b""):
    return (f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\n".encode() + extra
            + b"\r\n" + body)


class FakeStream(httpcore.AsyncNetworkStream):

    def __init__(self, backend, raw):
        self.backend, self.raw = backend, raw

    async def read(self, max_bytes, timeout=None):
        out, self.raw = self.raw[:max_bytes], self.raw[max_bytes:]
        return out

    async def write(self, buffer, timeout=None):
        self.backend.written += buffer

    async def aclose(self):
        pass

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.backend.sni.append(server_hostname)
        return self

    def get_extra_info(self, info):
        return None


class FakeBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, raw=None, exc=None):
        self.raw = raw if raw is not None else _http()
        self.exc, self.targets, self.sni, self.written = exc, [], [], b""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.targets.append((host, port))
        if self.exc:
            raise self.exc
        return FakeStream(self, self.raw)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError

    async def sleep(self, seconds):
        pass


class Resolver:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    async def __call__(self, host, port):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


async def call(url=URL, resolver=None, backend=None, policy=POLICY, **kw):
    be = backend or FakeBackend()
    r = resolver or Resolver(["93.184.216.34"])
    try:
        resp = await guarded_request("POST", url, policy=policy, dest_id="d1", json={"a": 1},
                                     resolver=r, network_backend=be, **kw)
    except Exception:
        raise
    return resp, be, r


async def test_happy_path_pins_ip_and_keeps_sni():
    resp, be, r = await call()
    assert resp.status == 200 and resp.body == b"ok" and not resp.truncated
    assert be.targets == [("93.184.216.34", 443)]
    assert be.sni == ["hooks.example.com"]
    assert b"Host: hooks.example.com" in be.written
    assert r.calls == 1


@pytest.mark.parametrize("addr", [
    "10.0.0.5", "172.16.3.4", "192.168.1.1", "127.0.0.1", "::1", "169.254.169.254",
    "169.254.1.1", "fe80::1", "100.64.0.1", "0.0.0.0", "::", "::ffff:127.0.0.1",
    "::ffff:10.1.2.3", "::ffff:169.254.169.254", "fc00::1", "fd12::1", "224.0.0.1",
    "ff02::1", "240.0.0.1", "2002:7f00:1::1", "64:ff9b::7f00:1", "::127.0.0.1",
    "::10.0.0.1",
])
async def test_non_global_address_refused(addr):
    be = FakeBackend()
    with pytest.raises(GuardBlocked) as ei:
        await call(resolver=Resolver([addr]), backend=be)
    assert ei.value.reason == "address" and be.targets == []


async def test_mixed_public_and_private_refused():
    be = FakeBackend()
    with pytest.raises(GuardBlocked):
        await call(resolver=Resolver(["93.184.216.34", "10.0.0.1"]), backend=be)
    assert be.targets == []


@pytest.mark.parametrize("url,reason", [
    ("http://hooks.example.com/x", "scheme"),
    ("https://user:pw@hooks.example.com/x", "userinfo"),
    ("https://user@hooks.example.com/x", "userinfo"),
    ("https://evil.com/x", "host"),
    ("https://evil.com\\@hooks.example.com/x", "url"),
    ("https://x.logic.azure.com.evil.com/x", "host"),
    ("https://evillogic.azure.com/x", "host"),
    ("https://logic.azure.com/x", "host"),
])
async def test_url_refused_before_io(url, reason):
    be, r = FakeBackend(), Resolver(["93.184.216.34"])
    with pytest.raises(GuardBlocked) as ei:
        await call(url=url, backend=be, resolver=r)
    assert ei.value.reason == reason and be.targets == [] and r.calls == 0


async def test_suffix_dot_boundary_allows_real_subdomain():
    resp, be, _ = await call(url="https://X.Logic.Azure.com./h")
    assert resp.status == 200 and be.sni == ["x.logic.azure.com"]


async def test_regex_full_match_and_any_host():
    pol = HostPolicy(pattern=r"[a-z0-9]+\.example\.org")
    await call(url="https://ab1.example.org/x", policy=pol)
    with pytest.raises(GuardBlocked):
        await call(url="https://ab1.example.org.evil.com/x", policy=pol)
    await call(url="https://anything.test/x", policy=HostPolicy(any_host=True))


async def test_ip_literal_goes_through_address_check():
    pol = HostPolicy(any_host=True)
    r = Resolver(["93.184.216.34"])
    for lit in ("https://127.0.0.1/x", "https://[::1]/x", "https://169.254.169.254/latest"):
        with pytest.raises(GuardBlocked) as ei:
            await call(url=lit, policy=pol, resolver=r)
        assert ei.value.reason == "address"
    assert r.calls == 0
    resp, be, _ = await call(url="https://93.184.216.34/x", policy=pol, resolver=r)
    assert be.targets == [("93.184.216.34", 443)] and r.calls == 0


async def test_redirect_blocked_not_followed():
    be = FakeBackend(raw=_http(302, b"", b"Location: https://evil.com/\r\n"))
    with pytest.raises(GuardBlocked) as ei:
        await call(backend=be)
    assert ei.value.reason == "redirect" and len(be.targets) == 1


async def test_dns_rebinding_connects_to_first_vetted_ip_resolver_once():
    r = Resolver(["93.184.216.34"], ["127.0.0.1"])
    resp, be, _ = await call(resolver=r)
    assert r.calls == 1 and be.targets == [("93.184.216.34", 443)]


async def test_allow_private_only_when_set():
    pol = HostPolicy(exact=("ntfy.lan",), allow_private=True)
    resp, be, _ = await call(url="https://ntfy.lan/t", policy=pol, resolver=Resolver(["192.168.1.9"]))
    assert be.targets == [("192.168.1.9", 443)]
    resp, be, _ = await call(url="https://ntfy.lan/t", policy=pol, resolver=Resolver(["127.0.0.1"]))
    assert be.targets == [("127.0.0.1", 443)]
    with pytest.raises(GuardBlocked):
        await call(url="https://ntfy.lan/t", policy=pol, resolver=Resolver(["169.254.169.254"]))
    with pytest.raises(GuardBlocked):
        await call(url="https://ntfy.lan/t", policy=HostPolicy(exact=("ntfy.lan",)),
                   resolver=Resolver(["192.168.1.9"]))


PLAIN = HostPolicy(any_host=True, allow_private=True, allow_plain_http=True, switchable=True)
LAN_URL = "http://ntfy.lan:8080/topic?x=SECRETQUERY"


async def test_plain_http_admitted_to_private_literal_and_pinned():
    resp, be, r = await call(url="http://192.168.1.9:8080/t", policy=PLAIN)
    assert resp.status == 200 and be.targets == [("192.168.1.9", 8080)] and be.sni == [] and r.calls == 0
    assert b"Host: 192.168.1.9:8080" in be.written


async def test_plain_http_to_private_name_pins_resolved_ip_and_sends_host():
    resp, be, r = await call(url=LAN_URL, policy=PLAIN, resolver=Resolver(["10.0.0.7"]))
    assert be.targets == [("10.0.0.7", 8080)] and r.calls == 1 and be.sni == []
    assert b"Host: ntfy.lan:8080" in be.written


@pytest.mark.parametrize("pol,reason", [
    (HostPolicy(any_host=True, allow_private=True, switchable=True), "plain_http"),
    (HostPolicy(any_host=True, switchable=True), "plain_http"),
    (HostPolicy(any_host=True, allow_plain_http=True, switchable=True), "private"),
    (HostPolicy(any_host=True, allow_private=True, switchable=True, origin_changed=True), "origin"),
])
async def test_plain_http_to_a_private_target_needs_both_switches(pol, reason):
    be, r = FakeBackend(), Resolver(["10.0.0.7"])
    with pytest.raises(GuardLocalPolicy) as ei:
        await call(url=LAN_URL, policy=pol, backend=be, resolver=r)
    assert ei.value.switch == reason and be.targets == []


@pytest.mark.parametrize("url,addr", [
    ("http://93.184.216.34/t", None),
    ("http://hooks.example.com/t", "93.184.216.34"),
    ("http://ntfy.lan/t", "169.254.169.254"),
    ("http://134744072/t", None),
])
@pytest.mark.parametrize("pol", [
    HostPolicy(any_host=True, switchable=True), HostPolicy(any_host=True, allow_private=True, switchable=True),
])
async def test_plain_http_to_a_public_or_refused_address_is_a_genuine_refusal_with_the_switches_off(pol, url, addr):
    be = FakeBackend()
    with pytest.raises(GuardBlocked) as ei:
        await call(url=url, policy=pol, backend=be, resolver=Resolver([addr]) if addr else None)
    assert ei.value.reason == "address" and not isinstance(ei.value, GuardLocalPolicy) and be.targets == []


async def test_a_kind_with_no_switch_never_gets_local_policy():
    pol = HostPolicy(exact=("hooks.slack.com",))
    with pytest.raises(GuardBlocked) as ei:
        await call(url="https://hooks.slack.com/x", policy=pol, resolver=Resolver(["10.1.1.1"]))
    assert not isinstance(ei.value, GuardLocalPolicy) and ei.value.reason == "address"
    with pytest.raises(GuardBlocked) as ei2:
        await call(url="http://hooks.slack.com/x", policy=pol, resolver=Resolver(["10.1.1.1"]))
    assert not isinstance(ei2.value, GuardLocalPolicy) and ei2.value.reason == "scheme"


@pytest.mark.parametrize("addr", ["fd00:ec2::254", "100.100.100.200", "192.0.0.192", "::ffff:100.100.100.200"])
@pytest.mark.parametrize("url", ["https://ntfy.lan/t", "http://ntfy.lan/t"])
async def test_the_metadata_trio_is_refused_with_both_switches_on(url, addr):
    be = FakeBackend()
    with pytest.raises(GuardBlocked) as ei:
        await call(url=url, policy=PLAIN, backend=be, resolver=Resolver([addr]))
    assert ei.value.reason == "address" and not isinstance(ei.value, GuardLocalPolicy) and be.targets == []


@pytest.mark.parametrize("host,expect", [
    ("134744072", "8.8.8.8"), ("0x8.0x8.0x8.0x8", "8.8.8.8"), ("0x08080808", "8.8.8.8"), ("010.1.1.1", "8.1.1.1"),
    ("127.1", "127.0.0.1"), ("8.8.8.8", "8.8.8.8"), ("[::1]", "::1"), ("ntfy.lan", None), ("0x8.example", None),
])
def test_ip_literal_reads_every_notation(host, expect):
    got = G.ip_literal(host)
    assert (str(got) if got is not None else None) == expect


def test_origin_of_makes_default_ports_explicit():
    assert G.origin_of("HTTP://NTFY.lan/x") == "http://ntfy.lan:80"
    assert G.origin_of("https://a.example:8443/p") == "https://a.example:8443"
    assert G.origin_of("http://[::1]:9/x") == "http://[::1]:9"
    assert G.origin_of("not a url") is None


async def test_plain_http_mixed_public_and_private_refused():
    be = FakeBackend()
    with pytest.raises(GuardBlocked):
        await call(url=LAN_URL, policy=PLAIN, backend=be, resolver=Resolver(["10.0.0.7", "93.184.216.34"]))
    assert be.targets == []


async def test_plain_http_redirect_still_blocked():
    be = FakeBackend(raw=_http(301, b"", b"Location: http://10.0.0.8/\r\n"))
    with pytest.raises(GuardBlocked) as ei:
        await call(url="http://10.0.0.7/t", policy=PLAIN, backend=be)
    assert ei.value.reason == "redirect" and len(be.targets) == 1


async def test_private_off_is_local_policy_but_metadata_is_not():
    pol = HostPolicy(exact=("ntfy.lan",), switchable=True)
    with pytest.raises(GuardLocalPolicy) as ei:
        await call(url="https://ntfy.lan/t", policy=pol, resolver=Resolver(["192.168.1.9"]))
    assert ei.value.reason == "address" and ei.value.switch == "private"
    with pytest.raises(GuardBlocked) as ei2:
        await call(url="https://ntfy.lan/t", policy=pol, resolver=Resolver(["169.254.169.254"]))
    assert not isinstance(ei2.value, GuardLocalPolicy)


async def test_body_truncated_at_64kib():
    big = b"x" * (70 * 1024)
    resp, _, _ = await call(backend=FakeBackend(raw=_http(200, big)))
    assert resp.truncated and len(resp.body) == 64 * 1024


async def test_basic_auth_and_form_data():
    be = FakeBackend()
    await guarded_request("POST", URL, policy=POLICY, dest_id="d", data={"k": "v"},
                          auth=("user", "pw"), resolver=Resolver(["93.184.216.34"]), network_backend=be)
    expect = b"authorization: Basic " + base64.b64encode(b"user:pw")
    assert expect in be.written
    assert b"k=v" in be.written


async def test_network_error_mapped():
    with pytest.raises(GuardNetworkError):
        await call(backend=FakeBackend(exc=httpcore.ConnectError("boom")))
    with pytest.raises(GuardTimeout):
        await call(backend=FakeBackend(exc=httpcore.ConnectTimeout("slow")))
    class Boom:
        async def __call__(self, h, p):
            raise G.GuardNetworkError("dns")
    with pytest.raises(GuardNetworkError):
        await call(resolver=Boom())


async def test_no_log_line_contains_path_or_query(caplog):
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as cap:
        await call()
        with pytest.raises(GuardBlocked):
            await call(resolver=Resolver(["10.0.0.1"]))
        with pytest.raises(GuardBlocked):
            await call(url="https://evil.com/SECRETPATHTOKEN?sig=SECRETQUERY")
    assert cap and {e["event"] for e in cap} >= {"guarded_http.response", "guarded_http.blocked"}
    blob = repr(cap) + caplog.text
    assert "SECRETPATHTOKEN" not in blob and "SECRETQUERY" not in blob
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_normalize_and_verdict_units():
    assert G.normalize_host("Bücher.Example.") == "xn--bcher-kva.example"
    assert G.address_verdict(__import__("ipaddress").ip_address("8.8.8.8"), allow_private=False)
