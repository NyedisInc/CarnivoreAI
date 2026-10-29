
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

CARRIED, DERIVED, EXCLUDED = "carried", "derived", "excluded"
PURGE_REMOVED, PURGE_KEPT = "removed", "kept"
ROLE_STORE, ROLE_BACKUP_DESTINATION = "store", "backup_destination"
BACKUP_VAULT, BACKUP_NONE = "vault", "none"
PROVIDES_BACKUP_POINTS = "backup_points"
_SCHEMA_FILE, _ENTRY_DEF = "item.schema.json", "data_entry"


@dataclass(frozen=True)
class DataPolicy:

    own: str
    share: str
    reason: str
    purge: str = ""
    backup: str = BACKUP_NONE


def default_store_root(state_dir: Path, default: str, sub: str = "") -> Path:
    base = Path(state_dir) / default
    return base / sub if sub else base


def is_default_value(state_dir: Path, default: str, value: Any, sub: str = "") -> bool:
    if not default or not isinstance(value, str) or not value.strip():
        return False
    return os.path.normpath(value.strip()) == os.path.normpath(str(default_store_root(state_dir, default, sub)))


@dataclass(frozen=True)
class DataDecl:

    id: str
    kind: str
    scope_by: str
    policy: DataPolicy
    path: str = ""
    root_setting: str = ""
    sub: str = ""
    secret_columns: Tuple[str, ...] = ()
    state_path: str = ""
    default: str = ""
    role: str = ROLE_STORE
    provides: str = ""

    @property
    def outlives_purge(self) -> bool:
        return self.policy.purge == PURGE_KEPT

    @property
    def wants_vault(self) -> bool:
        return self.policy.backup == BACKUP_VAULT

    def full_id(self, plugin_id: str) -> str:
        return f"{plugin_id}.{self.id}"


def problems_in(raw: Any, settings_fields: Mapping[str, Any]) -> List[str]:
    from src.cplugs.sdk.sidecar import schemas  # noqa: PLC0415

    if not isinstance(raw, list):
        return ["$.data: must be array"]
    problems: List[str] = []
    seen: set = set()
    provided: set = set()
    for i, entry in enumerate(raw):
        where = f"$.data[{i}]"
        found = schemas().validate_def(_SCHEMA_FILE, _ENTRY_DEF, entry, where)
        problems.extend(found)
        if found or not isinstance(entry, dict):
            continue
        if entry["id"] in seen:
            problems.append(f"{where}.id: '{entry['id']}' is declared twice")
        seen.add(entry["id"])
        setting = entry.get("root_setting")
        if setting is not None and setting not in settings_fields:
            problems.append(f"{where}.root_setting: '{setting}' is not a setting this plugin declares")
        if entry.get("path") is not None and entry["policy"].get("purge") == PURGE_KEPT:
            problems.append(f"{where}.policy.purge: a store inside the plugin folder is removed with it; 'kept' needs a root_setting or state_path")
        if entry.get("role") == ROLE_BACKUP_DESTINATION and (entry["kind"] != "folder" or "path" in entry):
            problems.append(f"{where}.role: a backup_destination is a folder the owner places (kind folder with a root_setting or state_path)")
        if entry["policy"].get("backup") == BACKUP_VAULT and (entry["kind"] != "folder" or entry.get("role") == ROLE_BACKUP_DESTINATION):
            problems.append(f"{where}.policy.backup: only a kind folder store that is not itself a backup_destination can be backed up into the vault")
        if entry.get("provides") is not None:
            if entry["kind"] != "folder":
                problems.append(f"{where}.provides: only a kind folder store can provide backup points")
            if entry["provides"] in provided:
                problems.append(f"{where}.provides: '{entry['provides']}' is already provided by another store of this plugin")
            provided.add(entry["provides"])
    return problems


def parse_data(raw: Any, settings_fields: Mapping[str, Any]) -> Tuple[DataDecl, ...]:
    problems = problems_in(raw, settings_fields)
    if problems:
        raise DataDeclError("; ".join(problems))
    return tuple(DataDecl(id=e["id"], kind=e["kind"], scope_by=e["scope_by"],
                          policy=DataPolicy(e["policy"]["own"], e["policy"]["share"], e["policy"]["reason"], e["policy"].get("purge", ""),
                                          e["policy"].get("backup", BACKUP_NONE)),
                          path=e.get("path", ""), root_setting=e.get("root_setting", ""), sub=e.get("sub", ""),
                          secret_columns=tuple(e.get("secret_columns", ())), state_path=e.get("state_path", ""),
                          default=e.get("default", ""), role=e.get("role", ROLE_STORE), provides=e.get("provides", "")) for e in raw)


def settings_fields_of(settings_schema: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    fields = settings_schema.get("fields", {}) if isinstance(settings_schema, Mapping) else {}
    return fields if isinstance(fields, Mapping) else {}


class DataDeclError(ValueError):
    pass
