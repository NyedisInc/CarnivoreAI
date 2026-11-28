
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

UPSTREAM_URL_HEADER = "x-argent-upstream-url"
UPSTREAM_KEY_HEADER = "x-argent-upstream-key"
PRIVATE_REASON = "upstream on a private network"
NOT_REGISTERED_REASON = "upstream not registered in argent"
NOT_READY_REASON = "chaining not ready"
ID_TAKEN_REASON = "session id taken in argent"
SELF_REGISTRATION_OFF_REASON = "argent self-registration is off"
DENIAL_REASONS = {"argent_upstream_not_registered": NOT_REGISTERED_REASON, "argent_upstream_private_network": PRIVATE_REASON,
                 "agent_session.id_taken": ID_TAKEN_REASON, "self_registration_disabled": SELF_REGISTRATION_OFF_REASON}
_PRIVATE_SUFFIXES = (".localhost", ".local", ".lan", ".home", ".internal", ".home.arpa")


def _host(url: str) -> str:
    try:
        return (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return ""


def is_private_network(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or "." not in host or host.endswith(_PRIVATE_SUFFIXES)
    return ip.is_private or ip.is_loopback or ip.is_unspecified or ip.is_link_local


def reason_for_denial(code: str) -> str:
    return DENIAL_REASONS.get(code, "")
