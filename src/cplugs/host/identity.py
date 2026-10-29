
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Dict, List, Optional

from src.core.json_artifact import atomic_write_json
from src.cplugs.host import state as owner_state
from src.cplugs.sdk.manifest import ID_PATTERN, RESERVED_IDS

INSTALL_NAME = re.compile(ID_PATTERN.pattern)
UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LEDGER_FILE = "installs.json"
LEDGER_VERSION = 1

HOST_WORDS = frozenset({"state", "safe-mode", "r", "restart", "kill"})
ROADMAP_IDS = frozenset({
    "archive", "stats", "budget", "github", "slack", "discord", "telegram", "sns", "unread", "share", "huddle",
    "deepsearch", "backup", "summarize", "save", "ntfy", "pushover", "nflow", "homeassistant", "spotify", "addons",
})
RESERVED_ROUTES = frozenset({"secrets", "restart", "kill", "purge", "grants", "ui"})

OWNER_PUBLISHER = "carnivore"

_lock = threading.RLock()


class LedgerUnreadable(Exception):
    pass


class InstallRefused(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class InstallRecord:

    name: str
    uuid: str
    catalog_id: str


def reserved_names(shipped_ids: Collection[str]) -> frozenset:
    return frozenset(RESERVED_IDS) | HOST_WORDS | ROADMAP_IDS | frozenset(shipped_ids)


def _ledger_path(state_dir: Path) -> Path:
    return Path(state_dir) / owner_state.STATE_DIR_NAME / LEDGER_FILE


def _read(state_dir: Path) -> Dict[str, Dict[str, str]]:
    path = _ledger_path(state_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise LedgerUnreadable(f"{path}: {exc}") from exc
    installs = data.get("installs") if isinstance(data, dict) else None
    if not isinstance(installs, dict):
        raise LedgerUnreadable(f"{path}: no installs object")
    for name, row in installs.items():
        if not (isinstance(row, dict) and isinstance(row.get("catalog_id"), str)
                and isinstance(row.get("uuid"), str) and UUID_PATTERN.match(row["uuid"])):
            raise LedgerUnreadable(f"{path}: bad row for {name!r}")
    return installs


def _write(state_dir: Path, installs: Dict[str, Dict[str, str]]) -> None:
    path = _ledger_path(state_dir)
    if not atomic_write_json(path, {"version": LEDGER_VERSION, "installs": installs}, log_event="cplug_install_ledger_write_failed"):
        raise owner_state.StateWriteFailed(str(path))


def lookup(state_dir: Path, name: str) -> Optional[InstallRecord]:
    row = _read(state_dir).get(name)
    return InstallRecord(name, row["uuid"], row["catalog_id"]) if row else None


def installs(state_dir: Path) -> List[InstallRecord]:
    return [InstallRecord(name, row["uuid"], row["catalog_id"]) for name, row in sorted(_read(state_dir).items())]


def register_install(state_dir: Path, name: str, catalog_id: str, shipped_ids: Collection[str]) -> InstallRecord:
    if not isinstance(name, str) or not INSTALL_NAME.match(name):
        raise InstallRefused("name_invalid", f"an install name must match {INSTALL_NAME.pattern}")
    owner = catalog_id == f"{OWNER_PUBLISHER}/{name}"
    if name in (frozenset(RESERVED_IDS) | HOST_WORDS if owner else reserved_names(shipped_ids)):
        raise InstallRefused("name_reserved", f"{name} is reserved")
    with _lock:
        installs = _read(state_dir)
        row = installs.get(name)
        held = InstallRecord(name, row["uuid"], row["catalog_id"]) if row else None
        if held is not None:
            if held.catalog_id == catalog_id:
                return held
            raise InstallRefused("name_taken", f"{name} is held by another plugin")
        record = InstallRecord(name, uuid.uuid4().hex, catalog_id)
        installs[name] = {"uuid": record.uuid, "catalog_id": record.catalog_id}
        _write(state_dir, installs)
        return record


def release_install(state_dir: Path, name: str) -> bool:
    with _lock:
        installs = _read(state_dir)
        if installs.pop(name, None) is None:
            return False
        _write(state_dir, installs)
        return True


def data_key(record: Optional[InstallRecord], first_party_id: Optional[str] = None) -> str:
    if record is not None:
        return record.uuid
    if first_party_id and ID_PATTERN.match(first_party_id):
        return first_party_id
    raise ValueError("a plugin key needs an install record or a first-party id")


def data_dir(state_dir: Path, key: str) -> Path:
    if not (UUID_PATTERN.match(key) or ID_PATTERN.match(key)):
        raise ValueError("not a plugin data key")
    return Path(state_dir) / owner_state.STATE_DIR_NAME / key


def keychain_service(key: str) -> str:
    return f"carnivore-cplug-{key}"
