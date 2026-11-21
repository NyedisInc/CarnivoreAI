
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Optional

from src.plugins.reviewboard.public.headers import header_values

HEADER = b"carnivore-board-link"
VISITOR_HEADER = b"carnivore-visitor"
REVISION_HEADER = b"carnivore-revision"
_REVISION = re.compile(r"r[1-9][0-9]{0,8}")
_VISITOR = re.compile(r"[A-Za-z0-9_-]{22}")
FORWARDED = b"x-forwarded-for"
IPV6_BUCKET_BITS = 64
_BRACKETED = re.compile(r"\[([0-9A-Fa-f:.]+)\](?::[0-9]{1,5})?")
_V4_PORT = re.compile(r"([0-9.]+):[0-9]{1,5}")
_PORT_SUFFIX = re.compile(r".+:[0-9]{1,5}")
_TOKEN = re.compile(r"pbl_[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}")


def token_from(scope: Any) -> Optional[str]:
    values = header_values(scope, HEADER)
    if len(values) != 1:
        return None
    try:
        text = values[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    return text if _TOKEN.fullmatch(text) else None


def reviewed_revision(scope: Any) -> Optional[str]:
    values = header_values(scope, REVISION_HEADER)
    if len(values) != 1:
        return None
    text = values[0].decode("ascii", errors="replace")
    return text if _REVISION.fullmatch(text) else None


def visitor_key(scope: Any) -> Optional[str]:
    values = header_values(scope, VISITOR_HEADER)
    if len(values) != 1:
        return None
    text = values[0].decode("ascii", errors="replace")
    return text if _VISITOR.fullmatch(text) else None


def _right_most(scope: Any) -> str:
    joined = b",".join(header_values(scope, FORWARDED)).decode("ascii", errors="ignore")
    return joined.rsplit(",", 1)[-1].strip()


def _without_port(entry: str) -> str:
    bracketed = _BRACKETED.fullmatch(entry) or _V4_PORT.fullmatch(entry)
    return bracketed.group(1) if bracketed else entry


def client_key(scope: Any) -> Optional[str]:
    try:
        address = ipaddress.ip_address(_without_port(_right_most(scope)))
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/{IPV6_BUCKET_BITS}", strict=False))
    return str(address)


@dataclass(frozen=True)
class ForwardedReport:

    peer: str
    present: bool
    copies: int
    shape: str


def forwarded_report(scope: Any) -> ForwardedReport:
    lines = header_values(scope, FORWARDED)
    entry = _right_most(scope)
    if not lines:
        shape = "missing"
    elif not entry:
        shape = "empty"
    else:
        shape = "has_port" if _PORT_SUFFIX.fullmatch(entry) else "not_an_ip"
    client = scope.get("client")
    return ForwardedReport(str(client[0]) if client else "unknown", bool(lines), len(lines), shape)
