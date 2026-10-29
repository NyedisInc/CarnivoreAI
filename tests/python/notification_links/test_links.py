
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.notifications import links
from src.core.phone_link.manager import PhoneLinkManager


def fake_manager(*, available=True, enabled=True, devices=1, host="abc.link.example"):
    return SimpleNamespace(
        available=available,
        pairing=SimpleNamespace(enabled=enabled, device_count=lambda: devices),
        public_host=lambda: host,
    )


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(bound="0.0.0.0", names=("mac", "mac.local"), ips=("10.0.0.5",), clock=None, calls=None):
    def machine_names():
        if calls is not None:
            calls.append(1)
        return frozenset(names)

    return links.LinkResolver(
        clock=clock or Clock(), bound_host=lambda: bound, machine_names=machine_names,
        ipv4_addresses=lambda: list(ips), port=lambda: 8123,
    )


def test_mobile_sync_wins_even_when_loopback_bound():
    r = make(bound="127.0.0.1").resolve_blocking(fake_manager())
    assert (r.kind, r.base, r.reason) == ("mobile_sync", "https://abc.link.example", "mobile_sync_ready")


@pytest.mark.parametrize("mgr", [
    None, fake_manager(available=False), fake_manager(enabled=False), fake_manager(devices=0), fake_manager(host=""),
])
def test_mobile_not_set_up_falls_through_with_reason(mgr):
    r = make().resolve_blocking(mgr)
    assert (r.kind, r.base, r.reason) == ("local_name", "http://mac.local:8123", "mobile_sync_not_set_up")


@pytest.mark.parametrize("bound", ["127.0.0.1", "localhost", "::1", "127.5.5.5"])
def test_loopback_bind_gives_none_despite_names_and_ips(bound):
    r = make(bound=bound).resolve_blocking(None)
    assert (r.kind, r.base, r.reason) == ("none", "", "bound_loopback_only")


def test_unknown_bind_is_no_link():
    assert make(bound=None).resolve_blocking(None).reason == "bound_host_unknown"


def test_no_local_name_uses_lan_ip_and_skips_loopback_ips():
    r = make(names=("mac",), ips=("127.0.0.1", "10.0.0.5")).resolve_blocking(None)
    assert (r.kind, r.base) == ("lan_ip", "http://10.0.0.5:8123")


def test_nothing_available_is_no_lan_address():
    r = make(names=(), ips=()).resolve_blocking(None)
    assert (r.kind, r.reason) == ("none", "no_lan_address")


def test_cache_holds_then_expires():
    clock, calls = Clock(), []
    r = make(clock=clock, calls=calls)
    r.resolve_blocking(None)
    clock.t += 59
    r.resolve_blocking(None)
    assert len(calls) == 1
    clock.t += 2
    r.resolve_blocking(None)
    assert len(calls) == 2


def test_deep_link_is_the_base_plus_the_session_path():
    assert links.deep_link("http://h:1/", "my-proj") == "http://h:1/session/my-proj"
    for slug in ("my-proj", "weird slug/../x?y#z"):
        assert links.deep_link("http://h:1/", slug) == "http://h:1" + links.session_path(slug)
    assert links.deep_link("", "a") is None
    assert links.session_path("a b") == "/session/a_b"


def test_public_host_prefers_custom_name_and_phone_routes_use_it():
    import inspect
    from src.api import phone_link_routes
    m = PhoneLinkManager.__new__(PhoneLinkManager)
    m.hostname = "link.example"
    m.custom = SimpleNamespace(live_host=lambda: "")
    assert m.public_host() == "link.example"
    m.custom = SimpleNamespace(live_host=lambda: "mine.example.com")
    assert m.public_host() == "mine.example.com"
    src = inspect.getsource(phone_link_routes)
    assert "_pair_host" not in src and "manager.public_host()" in src
