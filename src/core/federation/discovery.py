
from __future__ import annotations

import asyncio
import errno
import hashlib
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core import config_writer
from src.core.federation import bonjour
from src.core.hosts import roster_push

logger = structlog.get_logger()

SERVICE_TYPE = "_carnivore._tcp"
PROTOCOL_MAJOR = 1
SSH_PORT = 22
TXT_KEYS = ("p", "fid", "mid", "lp", "pn")
PACK_NAME_MAX = 32
_PACK_NAME_BAD = re.compile(r"[^A-Za-z0-9 ._-]")
PROBE_TIMEOUT_S = 2.0
FID_SHORT_LEN = 6
FID_MAX = 64
MAX_PEERS = 64
PROBE_CONCURRENCY = 32
PROBE_ADDRS_MAX = 4
_MID_SALT = "carnivore.federation.mid.v1:"

STATE_OFF = "off"
STATE_ADVERTISING = "advertising"
STATE_UNAVAILABLE = "unavailable"
STATE_REFUSED = "refused"

PEER_NEW = "new"
PEER_PINNED = "pinned"
PEER_IDENTITY_CHANGED = "identity_changed"


def hash_machine_id(platform_uuid: Optional[str]) -> str:
    if not platform_uuid:
        return ""
    return hashlib.sha256((_MID_SALT + platform_uuid).encode()).hexdigest()[:32]


def sanitize_pack_name(raw: object) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    text = " ".join(_PACK_NAME_BAD.sub("", " ".join(raw.split())).split())[:PACK_NAME_MAX].strip()
    return text or None


def validate_pack_name(raw: object) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("bad_pack_name")
    text = raw.strip()
    if len(text) > PACK_NAME_MAX or _PACK_NAME_BAD.search(text) or "  " in text:
        raise ValueError("bad_pack_name")
    return text or None


def build_txt_pairs(fid: Optional[str], platform_uuid: Optional[str],
                    link_port: Optional[int] = None, pack_name: Optional[str] = None) -> List[tuple]:
    pairs = [
        ("p", str(PROTOCOL_MAJOR)),
        ("fid", fid or ""),
        ("mid", hash_machine_id(platform_uuid)),
    ]
    if isinstance(link_port, int) and not isinstance(link_port, bool) and 1 <= link_port <= 65534:
        pairs.append(("lp", str(link_port)))
        name = sanitize_pack_name(pack_name)
        if name:
            pairs.append(("pn", name))
    return pairs


def parse_link_port(raw: object) -> Optional[int]:
    text = str(raw or "")
    if not (text.isascii() and text.isdigit()):
        return None
    value = int(text)
    return value if 1 <= value <= 65535 else None


BLOCKED_ERRNOS = frozenset({errno.EHOSTUNREACH, errno.ENETUNREACH})


class LocalNetworkBlocked(Exception):
    pass


async def _can_connect(address: str, port: int, timeout: float, failures: Optional[List[Optional[int]]] = None) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout)
    except (OSError, asyncio.TimeoutError) as exc:
        if failures is not None:
            failures.append(exc.errno if isinstance(exc, OSError) else None)
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def probe_join_ports(candidates: List[Dict[str, Any]],
                           timeout: float = PROBE_TIMEOUT_S) -> List[Dict[str, Any]]:
    failures: List[Optional[int]] = []
    gate = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def connect(addr: str, port: int) -> bool:
        async with gate:
            return await _can_connect(addr, port, timeout, failures)

    async def one(cand: Dict[str, Any]) -> Optional[str]:
        port = int(cand["lp"]) + 1
        if port > 65535:
            return None
        addrs = list(cand.get("addresses") or [])[:PROBE_ADDRS_MAX]
        results = await asyncio.gather(*(connect(a, port) for a in addrs))
        return next((a for a, ok in zip(addrs, results) if ok), None)

    found = await asyncio.gather(*(one(c) for c in candidates))
    if failures and not any(found) and all(e in BLOCKED_ERRNOS for e in failures):
        raise LocalNetworkBlocked()
    return [{**c, "join_address": addr} for c, addr in zip(candidates, found) if addr]


def read_pack_name(config_path: Path) -> Optional[str]:
    try:
        value = config_writer.read_config(config_path).get("federation", {}).get("pack_name")
    except (FileNotFoundError, ValueError, AttributeError):
        return None
    return sanitize_pack_name(value)


def write_pack_name(config_path: Path, name: Optional[str]) -> None:

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc.get("federation")
        if not isinstance(block, dict):
            block = {}
        if name:
            block["pack_name"] = name
        else:
            block.pop("pack_name", None)
        doc["federation"] = block
        return doc

    config_writer.commit(config_path, _mutate)


def write_settings(config_path: Path, advertise: Optional[bool], name: Optional[str], set_name: bool) -> None:

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc.get("federation")
        if not isinstance(block, dict):
            block = {}
        if advertise is not None:
            block["advertise"] = bool(advertise)
        if set_name:
            if name:
                block["pack_name"] = name
            else:
                block.pop("pack_name", None)
        doc["federation"] = block
        return doc

    config_writer.commit(config_path, _mutate)


def read_advertise(config_path: Path) -> bool:
    try:
        value = config_writer.read_config(config_path).get("federation", {}).get("advertise")
    except (FileNotFoundError, ValueError, AttributeError):
        return True
    return value if isinstance(value, bool) else True


def write_advertise(config_path: Path, enabled: bool) -> None:

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc.get("federation")
        if not isinstance(block, dict):
            block = {}
        block["advertise"] = bool(enabled)
        doc["federation"] = block
        return doc

    config_writer.commit(config_path, _mutate)


def read_pins(config_path: Path) -> Dict[str, str]:
    try:
        pins = config_writer.read_config(config_path).get("federation", {}).get("pinned_fids", {})
    except (FileNotFoundError, ValueError, AttributeError):
        return {}
    return {str(k): str(v) for k, v in pins.items()} if isinstance(pins, dict) else {}


def write_pin(config_path: Path, name: str, fid: str) -> None:

    def _mutate(doc: Dict[str, Any]) -> Dict[str, Any]:
        block = doc.get("federation") if isinstance(doc.get("federation"), dict) else {}
        pins = block.get("pinned_fids") if isinstance(block.get("pinned_fids"), dict) else {}
        pins[name] = fid
        block["pinned_fids"] = pins
        doc["federation"] = block
        return doc

    config_writer.commit(config_path, _mutate)


def local_host_name() -> str:
    try:
        out = subprocess.run(
            ["/usr/sbin/scutil", "--get", "LocalHostName"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or socket.gethostname().split(".")[0]


TESTSLOT_ENV = "CARNIVORE_TESTSRV_BONJOUR"
SLOT_MARKER_ENV = "CARNIVORE_SETTINGS_ENV_FILE"
_TESTSLOT_NAME = re.compile(r"testslot_[0-9]{1,2}")


def testslot_instance_name(environ: Mapping[str, str]) -> Optional[str]:
    if not environ.get(SLOT_MARKER_ENV):
        return None
    value = environ.get(TESTSLOT_ENV, "")
    return value if _TESTSLOT_NAME.fullmatch(value) else None


class Discovery:

    def __init__(
        self,
        *,
        config_path: Path,
        fid_provider: Callable[[], Optional[str]] = lambda: None,
        platform_uuid_provider: Callable[[], Optional[str]] = lambda: None,
        name_provider: Callable[[], str] = local_host_name,
        loader: Optional[Callable[[], object]] = None,
        link_port_provider: Callable[[], Optional[int]] = lambda: None,
        advertise_allowed: bool = True,
    ) -> None:
        self._advertise_allowed = advertise_allowed
        self._config_path = Path(config_path)
        self._fid = fid_provider
        self._fid_fallback: Optional[str] = None
        self._uuid = platform_uuid_provider
        self._name_provider = name_provider
        self._link_port = link_port_provider
        self._loader = loader
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._register_ref: Optional[bonjour.ServiceRef] = None
        self._browse_ref: Optional[bonjour.ServiceRef] = None
        self._resolving: Dict[str, bonjour.ServiceRef] = {}
        self._addr: Dict[str, bonjour.ServiceRef] = {}
        self._peers: Dict[str, Dict[str, Any]] = {}
        self._name = ""
        self._advertising_wanted = True
        self._state = STATE_OFF
        self._browse_state = "stopped"


    def _set(self, field: str, value: Any) -> None:
        if getattr(self, field) != value:
            setattr(self, field, value)
            roster_push.announce()

    @property
    def state(self) -> str:
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        self._set("_state", value)

    @property
    def browse_state(self) -> str:
        return self._browse_state

    @browse_state.setter
    def browse_state(self, value: str) -> None:
        self._set("_browse_state", value)

    @property
    def advertising_wanted(self) -> bool:
        return self._advertising_wanted

    @advertising_wanted.setter
    def advertising_wanted(self, value: bool) -> None:
        self._set("_advertising_wanted", value)


    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._name = self._name_provider()
        self.advertising_wanted = read_advertise(self._config_path)
        try:
            bonjour.get_library(self._loader)
        except bonjour.BonjourUnavailableError as exc:
            self.state = STATE_UNAVAILABLE
            self.browse_state = STATE_UNAVAILABLE
            logger.warning("federation_discovery_unavailable", error=str(exc))
            return
        try:
            self._browse_ref = bonjour.browse(SERVICE_TYPE, self._on_browse, loader=self._loader)
            self._watch(self._browse_ref)
            self.browse_state = "browsing"
        except bonjour.DNSServiceError as exc:
            self.browse_state = STATE_REFUSED
            logger.warning("federation_browse_failed", error=str(exc))
        self._sync_registration()

    def stop(self) -> None:
        self._drop_register()
        for ref in [self._browse_ref, *self._resolving.values(), *self._addr.values()]:
            self._release(ref)
        self._browse_ref = None
        self._resolving.clear()
        self._addr.clear()
        had_peers = bool(self._peers)
        self._peers.clear()
        if had_peers:
            roster_push.announce()
        self.browse_state = "stopped"
        if self.state != STATE_UNAVAILABLE:
            self.state = STATE_OFF
        self._loop = None

    def refresh_fid(self, fid: Optional[str]) -> None:
        self._fid_fallback = fid
        self._drop_register()
        self._sync_registration()

    def refresh_link_port(self) -> None:
        self._drop_register()
        self._sync_registration()

    def set_advertise(self, enabled: bool) -> None:
        self.advertising_wanted = bool(enabled)
        self._sync_registration()


    def txt_pairs(self) -> List[tuple]:
        return build_txt_pairs(self._fid() or self._fid_fallback, self._uuid(), self._link_port(), read_pack_name(self._config_path))

    def _sync_registration(self) -> None:
        if self.state == STATE_UNAVAILABLE or self._loop is None:
            return
        if not self.advertising_wanted or not self._advertise_allowed:
            self._drop_register()
            self.state = STATE_OFF
            return
        if self._register_ref is not None:
            return
        try:
            self._register_ref = bonjour.register(
                SERVICE_TYPE, self._name, SSH_PORT,
                bonjour.encode_txt(self.txt_pairs()), self._on_register,
                loader=self._loader,
            )
            self._watch(self._register_ref)
            self.state = STATE_ADVERTISING
        except (bonjour.DNSServiceError, ValueError) as exc:
            self.state = STATE_REFUSED
            logger.warning("federation_advertise_failed", error=str(exc))

    def _drop_register(self) -> None:
        self._release(self._register_ref)
        self._register_ref = None

    def _on_register(self, error_code: int, name: str, regtype: str, domain: str) -> None:
        if error_code != 0:
            self.state = STATE_REFUSED
            logger.warning("federation_advertise_refused", code=error_code)


    def _on_browse(self, error_code: int, flags: int, name: str, regtype: str, domain: str) -> None:
        if error_code != 0:
            logger.warning("federation_browse_error", code=error_code)
            return
        if not flags & bonjour.kDNSServiceFlagsAdd:
            if self._peers.pop(name, None) is not None:
                roster_push.announce()
            self._release(self._resolving.pop(name, None))
            self._release(self._addr.pop(name, None))
            return
        if name == self._name:
            return
        try:
            ref = bonjour.resolve(
                name, regtype, domain,
                lambda ec, full, host, port, txt: self._on_resolve(ec, name, host, port, txt),
                loader=self._loader,
            )
        except bonjour.DNSServiceError as exc:
            logger.warning("federation_resolve_failed", error=str(exc))
            return
        self._replace(self._resolving, name, ref)

    def _on_resolve(self, error_code: int, name: str, host: str, port: int, txt: bytes) -> None:
        self._retire(self._resolving, name)
        if error_code != 0:
            return
        record = bonjour.decode_txt(txt)
        mid = str(record.get("mid", ""))
        if mid and mid == hash_machine_id(self._uuid()):
            return
        peer = {
            "name": name, "host": host, "port": port, "addresses": [],
            "p": str(record.get("p", "")), "fid": str(record.get("fid", ""))[:FID_MAX], "mid": mid,
            "lp": parse_link_port(record.get("lp")),
            "pn": sanitize_pack_name(record.get("pn")),
        }
        if name not in self._peers and len(self._peers) >= MAX_PEERS:
            logger.warning("federation_peer_table_full")
            return
        self._peers[name] = peer
        roster_push.announce()
        try:
            ref = bonjour.get_addr_info(
                host, lambda ec, h, addrs: self._on_addr(ec, name, addrs), loader=self._loader,
            )
        except bonjour.DNSServiceError as exc:
            logger.warning("federation_addrinfo_failed", error=str(exc))
            return
        self._replace(self._addr, name, ref)

    def _on_addr(self, error_code: int, name: str, addrs: List[bonjour.DiscoveredAddress]) -> None:
        peer = self._peers.get(name)
        if peer is None or error_code != 0:
            return
        before = len(peer["addresses"])
        for a in addrs:
            if a.address not in peer["addresses"]:
                peer["addresses"].append(a.address)
        if len(peer["addresses"]) != before:
            roster_push.announce()

    def peer_state(self, peer: Dict[str, Any], pins: Dict[str, str]) -> str:
        pinned = pins.get(peer["name"])
        if pinned is None:
            return PEER_NEW
        return PEER_PINNED if pinned == peer["fid"] else PEER_IDENTITY_CHANGED

    def discovered(self, known_targets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        pins = read_pins(self._config_path)
        targets = {t.split("@")[-1].lower().removesuffix(".local") for t in (known_targets or [])}
        out = []
        for peer in sorted(self._peers.values(), key=lambda p: p["name"]):
            handles = {peer["name"].lower(), peer["host"].lower().rstrip(".").removesuffix(".local"),
                       *(a.lower() for a in peer["addresses"])}
            out.append({**peer, "addresses": list(peer["addresses"]),
                        "state": self.peer_state(peer, pins),
                        "known_host": bool(handles & targets)})
        return out

    def candidates(self) -> List[Dict[str, Any]]:
        out = []
        for peer in sorted(self._peers.values(), key=lambda p: p["name"]):
            if peer.get("lp") is None:
                continue
            addrs = list(peer["addresses"]) or ([peer["host"].rstrip(".")] if peer["host"] else [])
            out.append({"name": peer["name"], "fid": peer["fid"],
                        "fid_short": peer["fid"][:FID_SHORT_LEN], "addresses": addrs,
                        "lp": peer["lp"], "pack_name": peer.get("pn")})
        return out


    def _watch(self, ref: bonjour.ServiceRef) -> None:
        loop = self._loop
        if loop is not None:
            loop.add_reader(ref.fd, self._pump, ref)

    def _replace(self, table: Dict[str, bonjour.ServiceRef], name: str,
                 ref: bonjour.ServiceRef) -> None:
        self._release(table.pop(name, None))
        table[name] = ref
        self._watch(ref)

    def _retire(self, table: Dict[str, bonjour.ServiceRef], name: str) -> None:
        ref = table.pop(name, None)
        if ref is not None and self._loop is not None:
            self._loop.call_soon(self._release, ref)

    def _pump(self, ref: bonjour.ServiceRef) -> None:
        try:
            ref.process_result()
        except bonjour.DNSServiceError as exc:
            logger.warning("federation_dns_sd_pump_failed", error=str(exc))
            self._release(ref)

    def _release(self, ref: Optional[bonjour.ServiceRef]) -> None:
        if ref is None:
            return
        if self._loop is not None:
            try:
                self._loop.remove_reader(ref.fd)
            except (ValueError, OSError):
                pass
        ref.deallocate()
