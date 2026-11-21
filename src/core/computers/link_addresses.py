
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import sys
from typing import List, Optional, Tuple

from src.core.computers.join_identity import MAX_LISTEN_ADDRESSES, lan_address_ok

MAX_ADDRESSES = 6
_INET = re.compile(r"^\s+inet (\d{1,3}(?:\.\d{1,3}){3}) ", re.MULTILINE)
_IP4_LINE = re.compile(r"\binet (\d{1,3}(?:\.\d{1,3}){3})/\d+")
_IP_BINARIES = ("/sbin/ip", "/usr/sbin/ip", "/bin/ip")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _run(argv: List[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _platform() -> str:
    return sys.platform if sys.platform in ("darwin", "win32") else "linux"


def _default_route_address() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
    except OSError:
        return None


def _addresses_darwin() -> List[str]:
    return _INET.findall(_run(["/sbin/ifconfig", "-a"]))


def _addresses_linux() -> List[str]:
    for binary in _IP_BINARIES:
        text = _run([binary, "-4", "-o", "addr", "show"])
        if text:
            return _IP4_LINE.findall(text)
    return []


def _addresses_windows() -> List[str]:
    try:
        return [str(info[4][0]) for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def _ordered(texts: List[str], default: Optional[str]) -> List[str]:
    kept: List[str] = []
    for text in ([default] if default else []) + texts:
        if text not in kept and lan_address_ok(text):
            kept.append(text)
    rank = lambda t: 0 if t == default else 1 if ipaddress.ip_address(t) in _CGNAT else 2
    return sorted(kept, key=rank)


def local_addresses() -> List[str]:
    platform = _platform()
    out: List[str] = []
    if platform == "darwin":
        name = _run(["/usr/sbin/scutil", "--get", "LocalHostName"]).strip() or socket.gethostname().split(".")[0]
        out = [f"{name}.local"] if name and lan_address_ok(f"{name}.local") else []
    texts = {"darwin": _addresses_darwin, "win32": _addresses_windows}.get(platform, _addresses_linux)()
    return (out + _ordered(texts, _default_route_address()))[:MAX_ADDRESSES]


def learned_listen(addresses: List[str], port: Optional[int], *, join_port: int) -> Optional[Tuple[List[str], Optional[int]]]:
    kept: List[str] = []
    for text in addresses:
        if isinstance(text, str) and lan_address_ok(text) and text not in kept:
            kept.append(text)
    if not kept:
        return None
    kept.sort(key=lambda a: not a.lower().endswith(".local"))
    ok_port = port if isinstance(port, int) and not isinstance(port, bool) and 1024 <= port <= 65535 and port != join_port else None
    return kept[:MAX_LISTEN_ADDRESSES], ok_port
