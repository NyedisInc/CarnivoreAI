
from __future__ import annotations

import copy
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Dict, FrozenSet, List, Optional, Tuple

from src.core.plugin_registry import plugin_layout
from src.plugins.host import registry_store
from src.plugins.host import state as owner_state
from src.plugins.sdk.manifest import ID_PATTERN, RESERVED_IDS

INSTALL_NAME = re.compile(ID_PATTERN.pattern)
UUID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LEDGER_VERSION = 1

HOST_WORDS = frozenset({"state", "safe-mode", "r", "restart", "kill", "profiles"})
ROADMAP_IDS = frozenset({
    "archive", "stats", "budget", "github", "slack", "discord", "telegram", "sns", "unread", "share", "huddle",
    "deepsearch", "backup", "summarize", "save", "ntfy", "pushover", "n8n", "homeassistant", "spotify", "addons",
})
RETIRED_IDS: FrozenSet[str] = frozenset()
RESERVED_ROUTES = frozenset({"secrets", "restart", "kill", "purge", "grants", "ui"})

OWNER_PUBLISHER = "carnivore"
LOCAL_PUBLISHER = "local"
GITHUB_PUBLISHER = "github"
TIER_UNVERIFIED_GITHUB = "unverified_github"
PUBLISHER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,38}$")
RESERVED_PUBLISHERS = frozenset({LOCAL_PUBLISHER, GITHUB_PUBLISHER, "core", "cplug", "cplugs", "plugin", "plugins"})

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
    commit_sha: str = ""


def is_unverified_github(catalog_id: object) -> bool:
    return isinstance(catalog_id, str) and catalog_id.startswith(f"{GITHUB_PUBLISHER}/")


def trust_metadata(definition: Any) -> Dict[str, Any]:
    if not hasattr(definition, "item_id"):
        return {
            "kind": "plugin",
            "trust_tier": "builtin",
            "trust_badge": "Built-in",
            "unverified": False,
        }
    item_id = str(getattr(definition, "item_id", "") or "")
    tier = str(getattr(getattr(definition, "manifest", None), "tier", "") or "")
    if tier == LOCAL_PUBLISHER or item_id.startswith(f"{LOCAL_PUBLISHER}/"):
        return {
            "kind": "cplug",
            "trust_tier": "local_dev",
            "trust_badge": "Local Dev",
            "unverified": True,
        }
    if tier == TIER_UNVERIFIED_GITHUB or is_unverified_github(item_id):
        return {
            "kind": "cplug",
            "trust_tier": "unverified_github",
            "trust_badge": "Unverified GitHub Repo",
            "unverified": True,
        }
    return {
        "kind": "cplug",
        "trust_tier": "warez_verified",
        "trust_badge": "Warez Verified",
        "unverified": False,
    }


def check_catalog_id(catalog_id: object, name: str, shipped_ids: Collection[str], *, sideload: bool = False,
                     github: bool = False) -> Tuple[str, str]:
    if not isinstance(catalog_id, str) or unicodedata.normalize("NFC", catalog_id) != catalog_id or catalog_id != catalog_id.lower():
        raise InstallRefused("id_invalid", "a catalog id must be lower case, already in Unicode NFC")
    publisher, slash, tail = catalog_id.partition("/")
    if not slash or not PUBLISHER_PATTERN.match(publisher) or not INSTALL_NAME.match(tail):
        raise InstallRefused("id_invalid", f"a catalog id is <publisher>/<name> with a publisher matching {PUBLISHER_PATTERN.pattern} and a name matching {INSTALL_NAME.pattern}")
    if sideload and tail != name:
        raise InstallRefused("id_invalid", "a sideload's id is local/<its install name>")
    if github and tail != name:
        raise InstallRefused("id_invalid", "a direct GitHub install's id is github/<its install name>")
    if sideload:
        if publisher != LOCAL_PUBLISHER:
            raise InstallRefused("id_local_only", f"a sideload is always {LOCAL_PUBLISHER}/<name>")
    elif github:
        if publisher != GITHUB_PUBLISHER:
            raise InstallRefused("id_github_only", f"a direct GitHub install is always {GITHUB_PUBLISHER}/<name>")
    elif publisher == LOCAL_PUBLISHER:
        raise InstallRefused("id_local_only", f"{LOCAL_PUBLISHER}/ is for sideloads; a catalog item cannot use it")
    elif publisher == GITHUB_PUBLISHER:
        raise InstallRefused("id_github_only", f"{GITHUB_PUBLISHER}/ is for direct GitHub installs; a catalog item cannot use it")
    elif publisher in RESERVED_PUBLISHERS or publisher in shipped_ids:
        raise InstallRefused("publisher_reserved", f"{publisher} is a reserved publisher")
    return publisher, tail


def _record_of(name: str, row: Dict[str, str]) -> InstallRecord:
    return InstallRecord(
        name,
        row["uuid"],
        row["catalog_id"],
        row.get("publisher_key_id", ""),
        row.get("source", ""),
        row.get("commit_sha", ""),
    )


def _may_inherit(held: InstallRecord, publisher_key_id: str, source: str, sideload: bool, github: bool = False) -> bool:
    recorded, offered = (held.source, source) if (sideload or github) else (held.publisher_key_id, publisher_key_id)
    return recorded == "" or recorded == offered


def owner_refused(renamed_ids: Collection[str]) -> FrozenSet[str]:
    return frozenset(RESERVED_IDS) | HOST_WORDS | frozenset(renamed_ids)


def reserved_names(shipped_ids: Collection[str]) -> FrozenSet[str]:
    return frozenset(RESERVED_IDS) | HOST_WORDS | ROADMAP_IDS | RETIRED_IDS | frozenset(shipped_ids)


def _validate_row(path: Path, name: str, row: Any) -> Dict[str, Any]:
    if not (
        isinstance(row, dict)
        and isinstance(row.get("catalog_id"), str)
        and isinstance(row.get("uuid"), str)
        and UUID_PATTERN.match(row["uuid"])
        and all(isinstance(row.get(k, ""), str) for k in ("publisher_key_id", "source", "commit_sha"))
    ):
        raise LedgerUnreadable(f"{path}: bad row for {name!r}")
    return row


def _read(state_dir: Path) -> Dict[str, Dict[str, Any]]:
    path = registry_store.registry_path(state_dir)
    doc, status = registry_store.load_registry(state_dir)
    if status == registry_store.STATUS_MISSING:
        return {}
    if status == registry_store.STATUS_UNREADABLE or doc is None:
        raise LedgerUnreadable(f"{path}: registry unreadable")
    installs: Dict[str, Dict[str, Any]] = {}
    for name, item in doc.get("items", {}).items():
        if not isinstance(item, dict) or "install_uuid" not in item:
            continue
        row: Dict[str, Any] = {"uuid": item.get("install_uuid"), "catalog_id": item.get("catalog_id")}
        if "publisher_key_id" in item:
            row["publisher_key_id"] = item["publisher_key_id"]
        if isinstance(item.get("ledger_extra"), dict):
            row.update(copy.deepcopy(item["ledger_extra"]))
        installs[name] = _validate_row(path, name, row)
    for name, tomb in doc.get("tombstones", {}).items():
        if not isinstance(tomb, dict):
            raise LedgerUnreadable(f"{path}: bad tombstone for {name!r}")
        row = copy.deepcopy(tomb["ledger"]) if isinstance(tomb.get("ledger"), dict) else None
        if row is None:
            row = {"uuid": tomb.get("install_uuid"), "catalog_id": tomb.get("catalog_id")}
            if tomb.get("publisher_key_id"):
                row["publisher_key_id"] = tomb["publisher_key_id"]
            if tomb.get("removed_at") or tomb.get("version"):
                row["removed"] = {
                    "at": tomb.get("removed_at") or "",
                    "version": tomb.get("version") or "",
                    "publisher_key_id": tomb.get("publisher_key_id") or "",
                }
        installs[name] = _validate_row(path, name, row)
    return installs


def _doc_for_update(state_dir: Path) -> Dict[str, Any]:
    try:
        return registry_store.read_for_mutation(state_dir, log_event="cplug_install_ledger_unreadable")
    except registry_store.RegistryUnreadable as exc:
        raise LedgerUnreadable(str(exc)) from exc


def _save(state_dir: Path, doc: Dict[str, Any]) -> None:
    path = registry_store.registry_path(state_dir)
    if not registry_store.save_document(state_dir, doc, log_event="cplug_install_ledger_write_failed"):
        raise owner_state.StateWriteFailed(str(path))


def _apply_record(item: Dict[str, Any], record: InstallRecord) -> None:
    item["kind"] = registry_store.KIND_PLUGIN
    item["source"] = (
        registry_store.SOURCE_FOLDER
        if str(record.catalog_id).startswith(registry_store.LOCAL_PREFIX)
        else registry_store.SOURCE_CATALOG
    )
    item["catalog_id"] = record.catalog_id
    item["install_uuid"] = record.uuid
    if record.publisher_key_id:
        item["publisher_key_id"] = record.publisher_key_id
    else:
        item.pop("publisher_key_id", None)
    if record.source:
        item["source_path"] = record.source
    else:
        if "sideload_record" not in item:
            item.pop("source_path", None)
    extra = dict(item.get("ledger_extra") or {})
    if record.source:
        extra["source"] = record.source
    else:
        extra.pop("source", None)
    if record.commit_sha:
        extra["commit_sha"] = record.commit_sha
    else:
        extra.pop("commit_sha", None)
    if extra:
        item["ledger_extra"] = extra
    else:
        item.pop("ledger_extra", None)


def lookup(state_dir: Path, name: str) -> Optional[InstallRecord]:
    row = _read(state_dir).get(name)
    return _record_of(name, row) if row else None


def installs(state_dir: Path) -> List[InstallRecord]:
    return [_record_of(name, row) for name, row in sorted(_read(state_dir).items())]


def register_install(state_dir: Path, name: str, catalog_id: str, shipped_ids: Collection[str], *, publisher_key_id: str = "",
                     source: str = "", commit_sha: str = "", sideload: bool = False, github: bool = False, renamed_ids: Collection[str] = ()) -> InstallRecord:
    if not isinstance(name, str) or not INSTALL_NAME.match(name):
        raise InstallRefused("name_invalid", f"an install name must match {INSTALL_NAME.pattern}")
    owner = catalog_id == f"{OWNER_PUBLISHER}/{name}"
    if name in (owner_refused(renamed_ids) if owner else reserved_names(shipped_ids)):
        raise InstallRefused("name_reserved", f"{name} is reserved")
    check_catalog_id(catalog_id, name, shipped_ids, sideload=sideload, github=github)
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(name)
        held = _record_of(name, row) if row else None
        if held is not None:
            if held.catalog_id != catalog_id:
                raise InstallRefused("name_taken", f"the name {name} belongs to {held.catalog_id}; rename yours")
            if github and held.source and source and held.source != source:
                raise InstallRefused("name_taken", f"the name {name} belongs to GitHub repo {held.source}; uninstall first or rename yours")
            if _may_inherit(held, publisher_key_id, source, sideload, github=github):
                stamped = InstallRecord(
                    name,
                    held.uuid,
                    held.catalog_id,
                    held.publisher_key_id or publisher_key_id,
                    held.source or source,
                    commit_sha or held.commit_sha,
                )
                if stamped != held or "removed" in row:
                    doc = _doc_for_update(state_dir)
                    tomb = doc.setdefault("tombstones", {}).pop(name, None)
                    item = dict(doc.setdefault("items", {}).get(name) or {"unstored": True})
                    if isinstance(tomb, dict) and isinstance(tomb.get("sideload_record"), dict):
                        item.setdefault("sideload_record", copy.deepcopy(tomb["sideload_record"]))
                    _apply_record(item, stamped)
                    doc["items"][name] = item
                    if isinstance(tomb, dict) and isinstance(tomb.get("state"), dict):
                        owner_state._set_item_state(doc, name, tomb["state"])
                    _save(state_dir, doc)
                return stamped
        record = InstallRecord(name, uuid.uuid4().hex, catalog_id, publisher_key_id, source, commit_sha)
        doc = _doc_for_update(state_dir)
        doc.setdefault("tombstones", {}).pop(name, None)
        item = dict(doc.setdefault("items", {}).get(name) or {"unstored": True})
        _apply_record(item, record)
        doc["items"][name] = item
        _save(state_dir, doc)
        return record


def _row_of(record: InstallRecord) -> Dict[str, str]:
    row = {"uuid": record.uuid, "catalog_id": record.catalog_id}
    if record.publisher_key_id:
        row["publisher_key_id"] = record.publisher_key_id
    if record.source:
        row["source"] = record.source
    if record.commit_sha:
        row["commit_sha"] = record.commit_sha
    return row


def restore_install(state_dir: Path, previous: InstallRecord) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(previous.name)
        if row is None or row["catalog_id"] != previous.catalog_id or row["uuid"] == previous.uuid:
            return False
        doc = _doc_for_update(state_dir)
        item = doc.setdefault("items", {}).get(previous.name)
        if not isinstance(item, dict):
            return False
        _apply_record(item, previous)
        _save(state_dir, doc)
        return True


def release_install(state_dir: Path, name: str) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        if name not in installs:
            return False
        doc = _doc_for_update(state_dir)
        items = doc.setdefault("items", {})
        tombstones = doc.setdefault("tombstones", {})
        if tombstones.pop(name, None) is not None:
            _save(state_dir, doc)
            return True
        item = items.get(name)
        if isinstance(item, dict) and "install_uuid" in item:
            if item.get("unstored") is True and "sideload_record" not in item:
                del items[name]
            else:
                for k in ("install_uuid", "catalog_id", "publisher_key_id", "source", "source_path", "ledger_extra"):
                    item.pop(k, None)
                item["kind"] = registry_store.KIND_FEATURE
            _save(state_dir, doc)
            return True
        return False


def mark_removed(state_dir: Path, name: str, *, version: str, publisher_key_id: str, removed_at: str) -> bool:
    with registry_store.locked(state_dir, _lock, owner_state.StateWriteFailed):
        installs = _read(state_dir)
        row = installs.get(name)
        if row is None:
            return False
        doc = _doc_for_update(state_dir)
        items = doc.setdefault("items", {})
        tombstones = doc.setdefault("tombstones", {})
        removed_block = {"at": removed_at, "version": version, "publisher_key_id": publisher_key_id}
        item = items.pop(name, None)
        if isinstance(item, dict) and "install_uuid" in item:
            ledger_row: Dict[str, Any] = {**row, "removed": removed_block}
            stored_state = owner_state._extract_state_entry(item)
            tomb: Dict[str, Any] = {
                "catalog_id": item["catalog_id"],
                "install_uuid": item["install_uuid"],
                "publisher_key_id": publisher_key_id or item.get("publisher_key_id") or None,
                "version": version,
                "grants": list(stored_state.get("grants", [])) if isinstance(stored_state, dict) else [],
                "settings": dict(stored_state.get("settings", {})) if isinstance(stored_state, dict) else {},
                "removed_at": removed_at,
                "ledger": ledger_row,
            }
            if stored_state is not None:
                tomb["state"] = stored_state
            if isinstance(item.get("sideload_record"), dict):
                tomb["sideload_record"] = copy.deepcopy(item["sideload_record"])
            tombstones[name] = tomb
        elif isinstance(tombstones.get(name), dict):
            tomb = tombstones[name]
            tomb["version"] = version
            tomb["removed_at"] = removed_at
            tomb["publisher_key_id"] = publisher_key_id or tomb.get("publisher_key_id") or None
            if isinstance(tomb.get("ledger"), dict):
                tomb["ledger"]["removed"] = removed_block
            else:
                tomb["ledger"] = {**row, "removed": removed_block}
        else:
            return False
        _save(state_dir, doc)
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
