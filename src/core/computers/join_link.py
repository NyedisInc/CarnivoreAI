
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from urllib.parse import parse_qsl

from src.core.computers.invites import Invite, secret_from_link
from src.core.computers.join_proto import fp_server

_LINK_RE = re.compile(r"^carnivore://join/v1\?[A-Za-z0-9=&.,:_-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.:_-]{1,253}$")
_K_RE = re.compile(r"^[0-9a-f]{32}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class JoinLink:

    hosts: List[str]
    link_port: int
    k: str
    invite_id: str
    secret: bytes = field(repr=False)


def parse_link(text: str) -> Optional[JoinLink]:
    if not isinstance(text, str) or len(text) > 512 or not _LINK_RE.match(text):
        return None
    pairs = parse_qsl(text.split("?", 1)[1], keep_blank_values=True)
    fields: Dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            return None
        fields[key] = value
    if set(fields) != {"h", "p", "k", "i", "s"}:
        return None
    hosts = [h for h in fields["h"].split(",") if h]
    if not hosts or len(hosts) > 8 or not all(_HOST_RE.match(h) for h in hosts):
        return None
    if not (fields["p"].isascii() and fields["p"].isdigit()) or not 1 <= int(fields["p"]) <= 65534:
        return None
    secret = secret_from_link(fields["s"])
    if secret is None or not _K_RE.match(fields["k"].lower()) or not _ID_RE.match(fields["i"]):
        return None
    return JoinLink(hosts, int(fields["p"]), fields["k"].lower(), fields["i"], secret)


def build_link(addresses: Sequence[str], link_port: int, cert_der: bytes, invite: Invite) -> Optional[str]:
    hosts = [a for a in addresses if _HOST_RE.match(a)][:8]
    if not hosts:
        return None
    k = fp_server(cert_der).hex()[:32]
    return f"carnivore://join/v1?h={','.join(hosts)}&p={link_port}&k={k}&i={invite.id}&s={invite.link_secret}"
