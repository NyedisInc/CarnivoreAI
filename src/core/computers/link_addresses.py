
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from typing import List, Optional, Tuple

from src.core.computers.join_identity import MAX_LISTEN_ADDRESSES, lan_address_ok

MAX_ADDRESSES = 6
_INET = re.compile(r"^\s+inet (\d{1,3}(?:\.\d{1,3}){3}) ", re.MULTILINE)


def _run(argv: List[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def local_addresses() -> List[str]:
    name = _run(["/usr/sbin/scutil", "--get", "LocalHostName"]).strip() or socket.gethostname().split(".")[0]
    out: List[str] = [f"{name}.local"] if name and lan_address_ok(f"{name}.local") else []
    for text in _INET.findall(_run(["/sbin/ifconfig", "-a"])):
        try:
            addr = ipaddress.ip_address(text)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or text in out:
            continue
        out.append(text)
    return out[:MAX_ADDRESSES]


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
