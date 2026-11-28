
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.core.pack.machines import can_block
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.machines import settings_doc
from src.core.pack.machines.ddl import PACK_MACHINES_TABLE

STALE_SECONDS = 30.0
PERSIST_EVERY_SECONDS = 60.0
MAX_SNAPSHOT_BYTES = 16 * 1024

STATE_SELF, STATE_CONNECTED, STATE_STALE, STATE_WAITING = "self", "connected", "stale", "waiting"
STATE_OLDER, STATE_NOT_PAIRED, STATE_UNKNOWN = "older", "not_paired", "unknown"
REPORTED_STATES = ("connected", "disconnected", "connecting")
REPORTED_PREFIX = "reported_"


@dataclass
class PeerInfo:

    install_id: str
    label: str
    host_key: str
    link_state: str
    capabilities: List[str] = field(default_factory=list)


@dataclass
class Entry:

    install_id: str
    label: str = ""
    host_key: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    received_at: Optional[float] = None
    holds_master: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    members: List[Dict[str, str]] = field(default_factory=list)
    specs: Optional[Dict[str, Any]] = None
    persisted_at: float = 0.0
    from_store: bool = False


def snapshot_ok(snapshot: Any, expected_install_id: str) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get("install_id") != expected_install_id:
        return False
    try:
        return len(json.dumps(snapshot, separators=(",", ":"))) <= MAX_SNAPSHOT_BYTES
    except (TypeError, ValueError):
        return False


def clean_members(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and isinstance(item.get("install_id"), str) and item["install_id"]:
            member = {"install_id": item["install_id"][:64], "label": str(item.get("label") or "")[:64]}
            if item.get("state") in REPORTED_STATES:
                member["state"] = item["state"]
            out.append(member)
    return out[:64]


def _telemetry_snapshot(install_id: str, tel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    machine = tel.get("machine")
    if not isinstance(machine, dict) or not machine:
        return None
    gb = 1024.0**3
    mem_total = machine.get("memory_total_bytes")
    mem_used = machine.get("memory_used_bytes")
    disk_free = machine.get("disk_free_bytes")
    mem_total_gb = round(mem_total / gb, 1) if isinstance(mem_total, (int, float)) and mem_total > 0 else None
    mem_avail_gb = (
        round((mem_total - mem_used) / gb, 1)
        if isinstance(mem_total, (int, float)) and isinstance(mem_used, (int, float)) and mem_total >= mem_used
        else None
    )
    disk_free_gb = round(disk_free / gb, 1) if isinstance(disk_free, (int, float)) and disk_free >= 0 else None
    return {
        "install_id": install_id,
        "label": str(tel.get("label") or ""),
        "app_version": str(tel.get("app_version") or ""),
        "taken_at": tel.get("ts"),
        "cpu_percent": machine.get("cpu_percent"),
        "cpu_count": machine.get("cpu_count"),
        "memory_percent": machine.get("memory_percent"),
        "memory_used_bytes": mem_used,
        "memory_total_bytes": mem_total,
        "disk_percent": machine.get("disk_percent"),
        "disk_free_bytes": disk_free,
        "disk_total_bytes": machine.get("disk_total_bytes"),
        "load_1": machine.get("load_1"),
        "load_5": machine.get("load_5"),
        "load_15": machine.get("load_15"),
        "uptime_seconds": machine.get("uptime_seconds"),
        "live_agents": machine.get("live_agents"),
        "via_telemetry": True,
        "load": {
            "cores": machine.get("cpu_count"),
            "load_1": machine.get("load_1"),
            "load_5": machine.get("load_5"),
            "cpu_percent": machine.get("cpu_percent"),
            "memory_percent": machine.get("memory_percent"),
            "mem_total_gb": mem_total_gb,
            "mem_available_gb": mem_avail_gb,
            "disk_percent": machine.get("disk_percent"),
            "disk_free_gb": disk_free_gb,
            "uptime_seconds": machine.get("uptime_seconds"),
        },
    }


class Roster:

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.entries: Dict[str, Entry] = {}

    def record(self, install_id: str, *, label: str, snapshot: Dict[str, Any], holds_master: Optional[str]) -> Entry:
        entry = self.entries.setdefault(install_id, Entry(install_id))
        snapshot = can_block.clean_received(snapshot)
        entry.label = label or entry.label
        entry.snapshot, entry.received_at, entry.holds_master, entry.from_store = snapshot, self._clock(), holds_master, False
        entry.specs = snapshot.get("specs") if isinstance(snapshot.get("specs"), dict) else entry.specs
        entry.capabilities = [c for c in snapshot.get("capabilities", []) if isinstance(c, str)][:64]
        entry.members = clean_members(snapshot.get("members"))
        return entry

    def forget(self, install_id: str) -> None:
        self.entries.pop(install_id, None)

    def due_for_store(self, entry: Entry) -> bool:
        return self._clock() - entry.persisted_at >= PERSIST_EVERY_SECONDS

    def fresh(self, entry: Optional[Entry]) -> bool:
        return bool(entry and entry.snapshot is not None and entry.received_at is not None
                    and not entry.from_store and self._clock() - entry.received_at <= STALE_SECONDS)

    def peer_state(self, peer: PeerInfo) -> str:
        if peer.link_state != "connected":
            return peer.link_state or "disconnected"
        entry = self.entries.get(peer.install_id)
        if not caps_mod.has(peer.capabilities, caps_mod.CAP_MACHINE):
            return STATE_OLDER
        if entry is None or entry.snapshot is None or entry.from_store:
            return STATE_WAITING
        return STATE_CONNECTED if self.fresh(entry) else STATE_STALE

    def _named_state(self, entry: Entry, member: Dict[str, str]) -> str:
        if member.get("state") is None:
            return STATE_NOT_PAIRED
        return REPORTED_PREFIX + member["state"] if self.fresh(entry) else STATE_UNKNOWN

    def view(
        self,
        *,
        self_snapshot: Dict[str, Any],
        self_id: str,
        self_label: str,
        peers: Iterable[PeerInfo],
        settings: settings_doc.PackSettings,
        peer_telemetry: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        master = settings.master_install_id
        now = self._clock()
        telemetry_map = peer_telemetry or {}
        machines: List[Dict[str, Any]] = [{
            "install_id": self_id, "label": self_label, "host_key": "local", "is_self": True, "is_master": self_id == master,
            "paired": True, "state": STATE_SELF, "capabilities": caps_mod.names(), "specs": self_snapshot.get("specs"),
            "snapshot": self_snapshot, "age_seconds": 0, "holds_master": master,
        }]
        known = {self_id}
        disagree: List[str] = []
        for peer in peers:
            known.add(peer.install_id)
            entry = self.entries.get(peer.install_id)
            state = self.peer_state(peer)
            live = state == STATE_CONNECTED
            if entry and entry.holds_master and entry.holds_master != master and state in (STATE_CONNECTED, STATE_STALE):
                disagree.append(peer.label or peer.install_id)
            machines.append({
                "install_id": peer.install_id, "label": peer.label or (entry.label if entry else ""), "host_key": peer.host_key,
                "is_self": False, "is_master": peer.install_id == master, "paired": True, "state": state,
                "capabilities": peer.capabilities, "specs": entry.specs if entry else None,
                "snapshot": entry.snapshot if live and entry else None,
                "age_seconds": round(now - entry.received_at) if entry and entry.received_at else None,
                "holds_master": entry.holds_master if entry and not entry.from_store else None,
            })
        named: Dict[str, Tuple[str, str]] = {}
        for entry in sorted(self.entries.values(), key=lambda e: e.install_id != master):
            if entry.install_id not in known:
                continue
            for member in entry.members:
                if member["install_id"] in named and named[member["install_id"]][1] != STATE_NOT_PAIRED:
                    continue
                named[member["install_id"]] = (member["label"], self._named_state(entry, member))
        shown_unpaired = set()
        for install_id, (label, named_state) in sorted(named.items(), key=lambda kv: kv[1][0]):
            if install_id not in known:
                shown_unpaired.add(install_id)
                tel = telemetry_map.get(install_id)
                tel_snap = _telemetry_snapshot(install_id, tel) if isinstance(tel, dict) else None
                tel_ts = tel.get("ts") if isinstance(tel, dict) else None
                tel_age = max(0, round(now - float(tel_ts))) if tel_snap is not None and isinstance(tel_ts, (int, float)) else None
                machines.append({"install_id": install_id, "label": label, "host_key": None, "is_self": False,
                                 "is_master": install_id == master, "paired": False, "state": named_state,
                                 "capabilities": [], "specs": None, "snapshot": tel_snap, "age_seconds": tel_age,
                                 "holds_master": None})
        for install_id, tel in sorted(
            telemetry_map.items(),
            key=lambda kv: (str((kv[1] or {}).get("label") or kv[0]).lower(), kv[0]),
        ):
            if install_id in known or install_id in shown_unpaired or not isinstance(tel, dict):
                continue
            tel_snap = _telemetry_snapshot(install_id, tel)
            if tel_snap is None:
                continue
            tel_ts = tel.get("ts")
            tel_age = max(0, round(now - float(tel_ts))) if isinstance(tel_ts, (int, float)) else None
            machines.append({
                "install_id": install_id,
                "label": str(tel.get("label") or install_id),
                "host_key": None,
                "is_self": False,
                "is_master": install_id == master,
                "paired": False,
                "state": REPORTED_PREFIX + "connected",
                "capabilities": [],
                "specs": None,
                "snapshot": tel_snap,
                "age_seconds": tel_age,
                "holds_master": None,
            })
        return {"master_install_id": master, "self_install_id": self_id, "settings": settings.model_dump(mode="json"),
                "disagreement": disagree or None, "machines": machines, "taken_at": now}



def store_entry(conn: sqlite3.Connection, entry: Entry, *, is_self: bool = False) -> None:
    now = time.time()
    with conn:
        conn.execute(
            f"INSERT INTO {PACK_MACHINES_TABLE} (install_id, host_key, label, is_self, specs_json, last_snapshot_json, "
            "last_snapshot_at, capabilities_json, members_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(install_id) DO UPDATE SET host_key=excluded.host_key, label=excluded.label, specs_json=excluded.specs_json, "
            "last_snapshot_json=excluded.last_snapshot_json, last_snapshot_at=excluded.last_snapshot_at, "
            "capabilities_json=excluded.capabilities_json, members_json=excluded.members_json, updated_at=excluded.updated_at",
            (entry.install_id, entry.host_key, entry.label, 1 if is_self else 0, json.dumps(entry.specs),
             json.dumps(entry.snapshot), entry.received_at, json.dumps(entry.capabilities), json.dumps(entry.members), now))
    entry.persisted_at = time.time()


def load_entries(conn: sqlite3.Connection) -> List[Entry]:
    out: List[Entry] = []
    for row in conn.execute(f"SELECT install_id, host_key, label, specs_json, last_snapshot_json, last_snapshot_at, "
                            f"capabilities_json, members_json FROM {PACK_MACHINES_TABLE} WHERE is_self = 0"):
        try:
            out.append(Entry(row[0], label=row[2] or "", host_key=row[1], specs=json.loads(row[3] or "null"),
                             snapshot=json.loads(row[4] or "null"), received_at=row[5],
                             capabilities=json.loads(row[6] or "[]"), members=clean_members(json.loads(row[7] or "[]")),
                             from_store=True, persisted_at=time.time()))
        except ValueError:
            continue
    return out


def delete_entry(conn: sqlite3.Connection, install_id: str) -> None:
    with conn:
        conn.execute(f"DELETE FROM {PACK_MACHINES_TABLE} WHERE install_id = ?", (install_id,))
