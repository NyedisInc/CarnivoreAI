
from __future__ import annotations

import pytest

from src.cplugs.publicboard.settings import (DEFAULT_BIND, DEFAULT_PORT, SettingsError, check_settings, parse_bind, parse_hostnames, parse_port,
                                             parse_proxies, parse_settings)


def test_defaults_are_off_the_network_and_unconfigured() -> None:
    settings = parse_settings({})
    assert (settings.port, settings.bind) == (DEFAULT_PORT, DEFAULT_BIND) and settings.configured is False


def test_a_full_valid_set_is_configured() -> None:
    s = parse_settings({"port": 8190, "bindAddress": "10.0.0.6", "hostnames": "review.home.example.com, b.example.com", "trustedProxies": "203.0.113.11"})
    assert s.configured and s.hostnames == ("review.home.example.com", "b.example.com") and s.trusted_proxies == ("203.0.113.11",)


@pytest.mark.parametrize("port", [0, 80, 1023, 5000, 8000, 65536, -1, 8190.5, "8190", True, None])
def test_bad_ports_are_refused(port: object) -> None:
    with pytest.raises(SettingsError):
        parse_port(port)


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "localhost", "", "10.0.0.6/24", "224.0.0.1", None, "10.0.0"])
def test_bad_bind_addresses_are_refused(bind: object) -> None:
    with pytest.raises(SettingsError):
        parse_bind(bind)


@pytest.mark.parametrize("hosts", ["Review.Example.com", "review.example.com:8190", "review.example.com.", "10.0.0.6", "[::1]", "*.example.com",
                                   "-a.example.com", "a..example.com", "exa mple.com", "ex_ample.com", "a.b.123", "a" * 64 + ".com", 5])
def test_bad_hostnames_are_refused(hosts: object) -> None:
    with pytest.raises(SettingsError):
        parse_hostnames(hosts)


@pytest.mark.parametrize("proxies", ["203.0.113.0/24", "proxy.example.com", "127.0.0.1", "::1", "0.0.0.0", "::", "224.0.0.1", "203.0.113", 5])
def test_bad_trusted_proxies_are_refused(proxies: object) -> None:
    with pytest.raises(SettingsError):
        parse_proxies(proxies)


def test_lists_are_trimmed_deduplicated_and_empty_is_allowed() -> None:
    assert parse_hostnames(" a.example.com , a.example.com,, ") == ("a.example.com",)
    assert parse_proxies("") == () and parse_proxies("203.0.113.11, ::ffff:203.0.113.11") == ("203.0.113.11",)


def test_one_proxy_without_a_hostname_is_not_configured() -> None:
    assert parse_settings({"trustedProxies": "203.0.113.11"}).configured is False
    assert parse_settings({"hostnames": "a.example.com"}).configured is False


def test_the_host_check_refuses_a_bad_save_and_names_the_setting() -> None:
    assert check_settings({"port": 8000}).refusal.startswith("port")
    assert check_settings({"trustedProxies": "10.0.0.0/8"}).refusal.startswith("trustedProxies")
    assert check_settings({"bindAddress": "0.0.0.0"}).refusal.startswith("bindAddress")
    assert check_settings({"hostnames": "A.example.com"}).refusal.startswith("hostnames")
    assert check_settings({"port": 8190, "hostnames": "a.example.com"}).refusal == ""
    assert check_settings({}).refusal == ""
