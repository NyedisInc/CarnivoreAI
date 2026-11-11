
from __future__ import annotations

import dataclasses
from typing import Any

from src.cplugs.host import runtime
from src.cplugs.sdk import data_decl
from src.cplugs.sdk.definition import CplugDefinition

FIXTURE_ID = "boardfix"
SETTINGS = {"boardsRoot": {"kind": "string", "default": ""}}
_OWN = {"own": "carried", "share": "excluded", "reason": "the owner's own work"}
DECLARED = [
    {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "default": "review-boards", "scope_by": "task_item_id",
     "policy": {**_OWN, "purge": "kept", "backup": "vault"}},
    {"id": "drafts", "kind": "folder", "path": "drafts", "scope_by": "install", "policy": {**_OWN, "backup": "vault"}},
    {"id": "locks", "kind": "folder", "path": "locks", "scope_by": "install",
     "policy": {"own": "excluded", "share": "excluded", "reason": "lock files, meaningless elsewhere"}},
]


def definition() -> CplugDefinition:
    base = runtime.definitions()[0]
    fields = dict(SETTINGS)
    manifest = dataclasses.replace(base.manifest, id=FIXTURE_ID, name_key=f"cplug.{FIXTURE_ID}.name", data=data_decl.parse_data(DECLARED, fields),
                                   settings_schema={"version": 1, "fields": fields}, default_enabled=False)
    return CplugDefinition(manifest=manifest, filled_roots=("boards",))


def install_into_ship_list(monkeypatch: Any) -> CplugDefinition:
    fixture = definition()
    monkeypatch.setattr(runtime, "_definitions", tuple(runtime.definitions()) + (fixture,))
    return fixture
