
import pytest

from relay.config import RelayConfigError, settings_from_env
from tests.relay_v2_support import Issuer

BASE = {"RELAY_PUBLISH_TOKEN": "t"}


def keys(issuer: Issuer) -> str:
    from relay.auth import b64url

    return f"rt1:{b64url(issuer.pins['rt1'])}"


def test_defaults_are_off_direct_and_the_documented_port_and_domain():
    s = settings_from_env(BASE)
    assert (s.link_enabled, s.link_port, s.link_domain, s.link_proxy_protocol) == (
        False, 8443, "link.carnivore.ai", "off")


def test_enabled_settings_are_read_from_the_environment():
    env = {**BASE, "CARNIVORE_RELAY_ISSUER_KEYS": keys(Issuer()), "RELAY_LINK_ENABLED": "true",
           "RELAY_LINK_PORT": "443", "RELAY_LINK_PROXY_PROTOCOL": "Required", "RELAY_LINK_BEHIND_LB": "1",
           "RELAY_LINK_DOMAIN": "Link.Example.com"}
    s = settings_from_env(env)
    assert (s.link_enabled, s.link_port, s.link_domain, s.link_proxy_protocol) == (
        True, 443, "link.example.com", "required")


@pytest.mark.parametrize("extra", [
    {"RELAY_LINK_ENABLED": "1"},
    {"RELAY_LINK_PROXY_PROTOCOL": "maybe"},
    {"RELAY_LINK_DOMAIN": "not a domain"},
    {"RELAY_LINK_PORT": "0"},
    {"CARNIVORE_RELAY_ISSUER_KEYS": keys(Issuer()), "RELAY_LINK_ENABLED": "1",
     "RELAY_LINK_PROXY_PROTOCOL": "required"},
])
def test_bad_link_settings_are_refused(extra):
    with pytest.raises(RelayConfigError):
        settings_from_env({**BASE, **extra})
