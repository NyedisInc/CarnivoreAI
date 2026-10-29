
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Set

import structlog
from pydantic import ValidationError

from src.config.launch_profiles import LAUNCH_PROFILES_KEY
from src.core import config_migration, config_migration_steps, ui_preferences
from src.core.config_bundle import constants
from src.core.config_bundle.bundle import ConfigBundle, clean_pins, project
from src.core.config_bundle.merge import carry_secrets, deep_merge, diff, flatten
from src.core.config_bundle.redact import redact
from src.core.config_bundle.wrapper_merge import merge_wrappers
from src.core.launch_profiles import bundle_guard

logger = structlog.get_logger()

Mode = Literal["merge", "replace"]

AGENTS_KEY = "agents"
WRAPPERS_KEY = "wrappers"


class ImportRefused(Exception):

    def __init__(self, detail: Any, status_code: int = 422) -> None:
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code


@dataclass
class Prepared:

    sections: Dict[str, Any]
    ui_changes: Dict[str, Any]
    pins: Dict[str, str]
    stripped: List[str] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)


def _validation_paths(exc: ValidationError) -> List[str]:
    return [
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:20]
    ]


def _migrate_sections(bundle: ConfigBundle, sections: Dict[str, Any]) -> Dict[str, Any]:
    current = config_migration.CURRENT_CONFIG_VERSION
    if bundle.config_version > current:
        raise ImportRefused(
            "this file was made by a newer version of the app; update this install first"
        )
    if bundle.config_version == current:
        return sections
    needs_probe = bundle.config_version < 1
    has_cld = config_migration_steps.probe_shell_function("cld") if needs_probe else False
    has_cldor = config_migration_steps.probe_shell_function("cldor") if needs_probe else False
    migrated, changed = config_migration.migrate_config_dict(
        {**sections, "config_version": bundle.config_version}, has_cld, has_cldor
    )
    if not changed:
        raise ImportRefused("this file's settings are too old to migrate")
    logger.info("config_import_migrated", from_version=bundle.config_version, to_version=current)
    return {k: v for k, v in migrated.items() if k in constants.EXPORTED_SECTIONS}


def _validate_sections(sections: Mapping[str, Any]) -> None:
    from src.config.auth import AuthConfig

    try:
        AuthConfig.model_validate(dict(sections))
    except ValidationError as exc:
        raise ImportRefused(_validation_paths(exc)) from exc


def _refuse_ambiguous_wrapper_ids(sections: Mapping[str, Any]) -> None:
    agents = sections.get(AGENTS_KEY)
    rows = agents.get(WRAPPERS_KEY) if isinstance(agents, Mapping) else None
    if not isinstance(rows, list):
        return
    seen: Set[str] = set()
    problems: List[str] = []
    for index, row in enumerate(rows):
        wrapper_id = row.get("id") if isinstance(row, Mapping) else None
        if not isinstance(wrapper_id, str) or not wrapper_id.strip():
            problems.append(f"agents.wrappers.{index}.id: missing")
        elif wrapper_id in seen:
            problems.append(f"agents.wrappers.{index}.id: {wrapper_id!r} appears more than once")
        else:
            seen.add(wrapper_id)
    if problems:
        raise ImportRefused(problems)


def prepare(bundle: ConfigBundle) -> Prepared:
    if bundle.schema_version > constants.BUNDLE_SCHEMA_VERSION:
        raise ImportRefused(
            "this file was made by a newer version of the app; update this install first"
        )
    ignored = sorted(set(bundle.config) - set(constants.EXPORTED_SECTIONS))
    allowed = {k: v for k, v in bundle.config.items() if k in constants.EXPORTED_SECTIONS}
    sections, stripped = redact(allowed, "config")
    sections = _migrate_sections(bundle, sections)
    _refuse_ambiguous_wrapper_ids(sections)
    _validate_sections(sections)

    values = {
        k: v for k, v in bundle.ui_preferences.items() if k not in constants.REFUSED_PREFERENCE_FIELDS
    }
    values, stripped_prefs = redact(values, "ui_preferences")
    changes: Dict[str, Any] = {}
    if values:
        try:
            changes = ui_preferences.validate_changes(values)
        except ValueError as exc:
            raise ImportRefused(f"preferences: {exc}") from exc

    return Prepared(
        sections=sections,
        ui_changes=changes,
        pins=clean_pins(bundle.pinned_themes),
        stripped=sorted(stripped + stripped_prefs),
        ignored=ignored,
    )


def _merged_pins(current: Mapping[str, str], incoming: Mapping[str, str], mode: Mode) -> Dict[str, str]:
    return dict(incoming) if mode == "replace" else {**current, **incoming}


def _flatten_view(view: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out.update(flatten(view["config"], "config", 6))
    out.update(flatten(view["ui_preferences"], "ui_preferences", 1))
    out.update(flatten(view["pinned_themes"], "pinned_themes", 1))
    return out


@dataclass(frozen=True)
class Built:

    document: Optional[Dict[str, Any]]
    preview: Dict[str, Any]
    pins_after: Dict[str, str]
    moved: Dict[str, Any]
    values: Dict[str, Any]
    revision: int


def build_document(
    doc: Mapping[str, Any],
    pins_now: Mapping[str, str],
    prepared: Prepared,
    mode: Mode,
) -> Built:
    candidate = dict(doc)
    for name, incoming in prepared.sections.items():
        existing = doc.get(name)
        if name == LAUNCH_PROFILES_KEY:
            candidate[name] = bundle_guard.merge_block(existing, incoming)
            continue
        merged = deep_merge(existing, incoming) if mode == "merge" else incoming
        candidate[name] = carry_secrets(existing, merged)
        if name == AGENTS_KEY and isinstance(candidate[name], dict):
            local_wrappers = existing.get(WRAPPERS_KEY) if isinstance(existing, Mapping) else None
            candidate[name] = {**candidate[name],
                               WRAPPERS_KEY: merge_wrappers(local_wrappers, candidate[name].get(WRAPPERS_KEY))}

    changes = dict(prepared.ui_changes)
    if mode == "replace":
        held = ui_preferences.read_block(dict(doc))["values"]
        for name in held:
            if name not in changes and name not in constants.REFUSED_PREFERENCE_FIELDS:
                changes[name] = None
    moved: Dict[str, Any] = {}
    if changes:
        candidate, _block, moved = ui_preferences.apply_changes(candidate, changes)
    block = ui_preferences.read_block(candidate)

    pins_after = _merged_pins(clean_pins(pins_now), prepared.pins, mode)
    preview = diff(
        _flatten_view(project(doc, pins_now)),
        _flatten_view(project(candidate, pins_after)),
    )
    return Built(
        document=None if candidate == dict(doc) else candidate,
        preview=preview,
        pins_after=pins_after,
        moved=moved,
        values=block["values"],
        revision=block["revision"],
    )
