
from __future__ import annotations

import copy
import ipaddress
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core import config_writer

KEY = "pack_reconnect"
DEFAULT_ON = False
TAKEOVER_DEFAULT_ON = False
_RELAY_ID = re.compile(r"[a-z0-9]{1,63}")
MAX_REMEMBERED = 16
MAX_SUBNETS = 3


def valid_relay_id(value: Any) -> bool:
    return isinstance(value, str) and _RELAY_ID.fullmatch(value) is not None


_BLOCKS: Dict[str, Tuple[Tuple[int, int, int], Dict[str, Any]]] = {}
_BLOCKS_LOCK = threading.Lock()


def _block(config_path: Path) -> Dict[str, Any]:
    key = str(config_path)
    try:
        st = Path(config_path).expanduser().stat()
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    with _BLOCKS_LOCK:
        held = _BLOCKS.get(key)
    if held is not None and held[0] == stamp:
        return copy.deepcopy(held[1])
    try:
        block = config_writer.read_config(config_path).get(KEY)
    except (OSError, ValueError, AttributeError):
        return {}
    block = block if isinstance(block, dict) else {}
    with _BLOCKS_LOCK:
        _BLOCKS[key] = (stamp, block)
    return copy.deepcopy(block)


def relay_choice(config_path: Path) -> Optional[bool]:
    value = _block(config_path).get("relay")
    return value if isinstance(value, bool) else None


def relay_on(config_path: Path) -> bool:
    choice = relay_choice(config_path)
    return DEFAULT_ON if choice is None else choice


def set_relay(config_path: Path, value: Optional[bool]) -> None:
    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        block = data.get(KEY) if isinstance(data.get(KEY), dict) else {}
        data[KEY] = {**block, "relay": value}
        return data

    config_writer.commit(config_path, mutate)


def takeover_on(config_path: Path) -> bool:
    value = _block(config_path).get("takeover")
    return TAKEOVER_DEFAULT_ON if not isinstance(value, bool) else value


def set_takeover(config_path: Path, value: Optional[bool]) -> None:
    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        block = data.get(KEY) if isinstance(data.get(KEY), dict) else {}
        data[KEY] = {**block, "takeover": value}
        return data

    config_writer.commit(config_path, mutate)


def learned_relay_id(config_path: Path, alpha_iid: str) -> Optional[str]:
    value = (_block(config_path).get("relay_ids") or {}).get(alpha_iid)
    return value if valid_relay_id(value) else None


def remember_relay_id(config_path: Path, alpha_iid: str, relay_id: str) -> bool:
    if not valid_relay_id(relay_id) or learned_relay_id(config_path, alpha_iid) == relay_id:
        return False

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        block = data.get(KEY) if isinstance(data.get(KEY), dict) else {}
        ids = {k: v for k, v in (block.get("relay_ids") or {}).items() if k != alpha_iid}
        data[KEY] = {**block, "relay_ids": {**dict(list(ids.items())[-(MAX_REMEMBERED - 1):]), alpha_iid: relay_id}}
        return data

    config_writer.commit(config_path, mutate)
    return True


def known_subnets(config_path: Path) -> List[str]:
    out: List[str] = []
    for text in _block(config_path).get("subnets") or []:
        try:
            net = ipaddress.ip_network(text, strict=False)
        except (ValueError, TypeError):
            continue
        if net.version == 4 and str(net) not in out:
            out.append(str(net))
    return out[-MAX_SUBNETS:]


def remember_subnet(config_path: Path, cidr: str) -> bool:
    if known_subnets(config_path)[-1:] == [cidr]:
        return False

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        block = data.get(KEY) if isinstance(data.get(KEY), dict) else {}
        current = [c for c in known_subnets(config_path) if c != cidr]
        data[KEY] = {**block, "subnets": (current + [cidr])[-MAX_SUBNETS:]}
        return data

    config_writer.commit(config_path, mutate)
    return True
