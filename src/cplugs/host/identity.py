
from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Dict, List, Optional, Tuple

from src.core import plugin_layout
from src.cplugs.host import registry_files, registry_store
from src.cplugs.host import state as owner_state
from src.cplugs.sdk.manifest import ID_PATTERN, RESERVED_IDS

INSTALL_NAME = re.compile(ID_PATTERN.pattern)
UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LEDGER_FILE = registry_store.LEDGER_FILE
LEDGER_VERSION = 1

HOST_WORDS = frozenset({"state", "safe-mode", "r", "restart", "kill", "profiles"})
ROADMAP_IDS = frozenset({
    "archive", "stats", "budget", "github", "slack", "discord", "telegram", "sns", "unread", "share", "huddle",
    "deepsearch", "backup", "summarize", "save", "ntfy", "pushover", "n8n", "homeassistant", "spotify", "addons",
})
RESERVED_ROUTES = frozenset({"secrets", "restart", "kill", "purge", "grants", "ui"})

OWNER_PUBLISHER = "carnivore"
LOCAL_PUBLISHER = "local"
PUBLISHER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}$")
RESERVED_PUBLISHERS = frozenset({LOCAL_PUBLISHER, "core", "cplug", "cplugs", "plugin", "plugins"})

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
    publisher_key_id: str = ""
    source: str = ""


def check_catalog_id(catalog_id: object, name: str, shipped_ids: Collection[str], *, sideload: bool = False) -> Tuple[str, str]:
    if not isinstance(catalog_id, str) or unicodedata.normalize("NFC", catalog_id) != catalog_id or catalog_id != catalog_id.lower():
        raise InstallRefused("id_invalid", "a catalog id must be lower case, already in Unicode NFC")
    publisher, slash, tail = catalog_id.partition("/")
    if not slash or not PUBLISHER_PATTERN.match(publisher) or not INSTALL_NAME.match(tail):
        raise InstallRefused("id_invalid", f"a catalog id is <publisher>/<name> with a publisher matching {PUBLISHER_PATTERN.pattern} and a name matching {INSTALL_NAME.pattern}")
    if sideload and tail != name:
        raise InstallRefused("id_invalid", "a sideload's id is local/<its install name>")
    if sideload:
        if publisher != LOCAL_PUBLISHER:
            raise InstallRefused("id_local_only", f"a sideload is always {LOCAL_PUBLISHER}/<name>")
    elif publisher == LOCAL_PUBLISHER:
        raise InstallRefused("id_local_only", f"{LOCAL_PUBLISHER}/ is for sideloads; a catalog item cannot use it")
    elif publisher in RESERVED_PUBLISHERS or publisher in shipped_ids:
        raise InstallRefused("publisher_reserved", f"{publisher} is a reserved publisher")
    return publisher, tail


def _record_of(name: str, row: Dict[str, str]) -> InstallRecord:
    return InstallRecord(name, row["uuid"], row["catalog_id"], row.get("publisher_key_id", ""), row.get("source", ""))


def _may_inherit(held: InstallRecord, publisher_key_id: str, source: str, sideload: bool) -> bool:
    recorded, offered = (held.source, source) if sideload else (held.publisher_key_id, publisher_key_id)
    return recorded == "" or recorded == offered


def reserved_names(shipped_ids: Collection[str]) -> frozenset:
    return frozenset(RESERVED_IDS) | HOST_WORDS | ROADMAP_IDS | frozenset(shipped_ids)


def _ledger_path(state_dir: Path) -> Path:
    return Path(state_dir) / owner_state.STATE_DIR_NAME / LEDGER_FILE


def _read(state_dir: Path) -> Dict[str, Dict[str, str]]:
    path = _ledger_path(state_dir)
    views = registry_files.flipped_copy(state_dir, "installs")
    try:
        data = views if views is not None else json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise LedgerUnreadable(f"{path}: {exc}") from exc
    installs = data.get("installs") if isinstance(data, dict) else None
    if not isinstance(installs, dict):
        raise LedgerUnreadable(f"{path}: no installs object")
    for name, row in installs.items():
        if not (isinstance(row, dict) and isinstance(row.get("catalog_id"), str)
                and isinstance(row.get("uuid"), str) and UUID_PATTERN.match(row["uuid"])
                and all(isinstance(row.get(k, ""), str) for k in ("publisher_key_id", "source"))):
            raise LedgerUnreadable(f"{path}: bad row for {name!r}")
    return installs


def _write(state_dir: Path, installs: Dict[str, Dict[str, str]]) -> None:
    path = _ledger_path(state_dir)
    if not registry_store.write_document(state_dir, "installs", {"version": LEDGER_VERSION, "installs": installs}, log_event="cplug_install_ledger_write_failed"):
        raise owner_state.StateWriteFailed(str(path))


def lookup(state_dir: Path, name: str) -> Optional[InstallRecord]:
    row = _read(state_dir).get(name)
    return _record_of(name, row) if row else None


def installs(state_dir: Path) -> List[InstallRecord]:
    return [_record_of(name, row) for name, row in sorted(_read(state_dir).items())]


def register_install(state_dir: Path, name: str, catalog_id: str, shipped_ids: Collection[str], *, publisher_key_id: str = "",
                     source: str = "", sideload: bool = False) -> InstallRecord:
    if not isinstance(name, str) or not INSTALL_NAME.match(name):
        raise InstallRefused("name_invalid", f"an install name must match {INSTALL_NAME.pattern}")
    owner = catalog_id == f"{OWNER_PUBLISHER}/{name}"
    if name in (frozenset(RESERVED_IDS) | HOST_WORDS if owner else reserved_names(shipped_ids)):
        raise InstallRefused("name_reserved", f"{name} is reserved")
    check_catalog_id(catalog_id, name, shipped_ids, sideload=sideload)
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(name)
        held = _record_of(name, row) if row else None
        if held is not None:
            if held.catalog_id != catalog_id:
                raise InstallRefused("name_taken", f"the name {name} belongs to {held.catalog_id}; rename yours")
            if _may_inherit(held, publisher_key_id, source, sideload):
                stamped = InstallRecord(name, held.uuid, held.catalog_id, held.publisher_key_id or publisher_key_id, held.source or source)
                if stamped != held or "removed" in row:
                    installs[name] = _row_of(stamped)
                    _write(state_dir, installs)
                return stamped
        record = InstallRecord(name, uuid.uuid4().hex, catalog_id, publisher_key_id, source)
        installs[name] = _row_of(record)
        _write(state_dir, installs)
        return record


def _row_of(record: InstallRecord) -> Dict[str, str]:
    row = {"uuid": record.uuid, "catalog_id": record.catalog_id}
    if record.publisher_key_id:
        row["publisher_key_id"] = record.publisher_key_id
    if record.source:
        row["source"] = record.source
    return row


def restore_install(state_dir: Path, previous: InstallRecord) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(previous.name)
        if row is None or row["catalog_id"] != previous.catalog_id or row["uuid"] == previous.uuid:
            return False
        installs[previous.name] = _row_of(previous)
        _write(state_dir, installs)
        return True


def release_install(state_dir: Path, name: str) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        if installs.pop(name, None) is None:
            return False
        _write(state_dir, installs)
        return True


def mark_removed(state_dir: Path, name: str, *, version: str, publisher_key_id: str, removed_at: str) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(name)
        if row is None:
            return False
        installs[name] = {**row, "removed": {"at": removed_at, "version": version, "publisher_key_id": publisher_key_id}}
        _write(state_dir, installs)
        return True


def removal_of(state_dir: Path, name: str) -> Optional[Dict[str, str]]:
    row = _read(state_dir).get(name)
    found = row.get("removed") if row else None
    return {k: str(v) for k, v in found.items()} if isinstance(found, dict) else None


def data_key(record: Optional[InstallRecord], first_party_id: Optional[str] = None) -> str:
    if record is not None:
        return record.uuid
    if first_party_id and ID_PATTERN.match(first_party_id):
        return first_party_id
    raise ValueError("a plugin key needs an install record or a first-party id")


def data_dir(state_dir: Path, key: str) -> Path:
    if not (UUID_PATTERN.match(key) or ID_PATTERN.match(key)):
        raise ValueError("not a plugin data key")
    return plugin_layout.data_root(state_dir, key)


def keychain_service(key: str) -> str:
    return f"carnivore-cplug-{key}"
