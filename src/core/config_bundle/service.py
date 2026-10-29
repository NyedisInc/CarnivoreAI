
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core import config_writer
from src.core.launch_profiles import bundle_guard
from src.core.config_bundle import command_guard
from src.core.config_bundle.bundle import ConfigBundle, clean_pins
from src.config.launch_profiles import LAUNCH_PROFILES_KEY
from src.core.config_bundle.importer import (
    AGENTS_KEY,
    WRAPPERS_KEY,
    Built,
    ImportRefused,
    Mode,
    Prepared,
    build_document,
    prepare,
)

logger = structlog.get_logger()

APPLIED = "applied"
PREVIEW = "preview"
UNCHANGED = "unchanged"


def _summary(bundle: ConfigBundle, prepared: Prepared, host: str) -> Dict[str, Any]:
    return {
        "source": {
            "schema_version": bundle.schema_version,
            "app_version": bundle.app_version,
            "config_version": bundle.config_version,
            "exported_at": bundle.exported_at,
            "source_host": bundle.source_host,
            "from_other_host": bool(bundle.source_host) and bundle.source_host != host,
        },
        "stripped": prepared.stripped,
        "ignored": prepared.ignored,
    }


_COMMAND_GATES: Tuple[Tuple[str, str, Callable[[Any, Any], List[Dict[str, Any]]], str], ...] = (
    ("agents", "wrappers", command_guard.written_commands, "agent commands"),
    ("workspace", "rows", command_guard.written_workspace, "a shell, editor or environment for new terminals"),
    ("browser", "rows", command_guard.written_browser, "a browser program"),
    ("provider_accounts", "rows", command_guard.written_account_dirs, "an agent config folder"),
    ("common_slash_commands", "rows", command_guard.written_slash_commands, "slash commands sent to agents"),
    ("template_path", "rows", command_guard.written_template_path, "a template folder copied into new projects"),
)


def _written_commands(doc: Dict[str, Any], built: Built) -> Dict[str, List[Dict[str, Any]]]:
    after = built.document if built.document is not None else doc
    found: Dict[str, List[Dict[str, Any]]] = {}
    for section, _key, guard, _words in _COMMAND_GATES:
        rows = guard(doc.get(section), after.get(section))
        if rows:
            found[section] = rows
    return found


_KEPT_LISTS: Tuple[Tuple[str, str], ...] = ((AGENTS_KEY, WRAPPERS_KEY), (LAUNCH_PROFILES_KEY, "profiles"))


def _ids(block: Any, key: str) -> List[str]:
    rows = block.get(key) if isinstance(block, Mapping) else None
    return [str(row.get("id")) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _kept_count(doc: Mapping[str, Any], prepared: Prepared) -> int:
    kept = 0
    for section, key in _KEPT_LISTS:
        if section in prepared.sections:
            incoming = set(_ids(prepared.sections[section], key))
            kept += sum(1 for row_id in _ids(doc.get(section), key) if row_id not in incoming)
    return kept


def _refuse_unconfirmed(written: Dict[str, List[Dict[str, Any]]], confirms: Dict[str, Optional[str]]) -> None:
    for section, _key, _guard, words in _COMMAND_GATES:
        rows = written.get(section)
        if rows and confirms.get(section) != command_guard.digest(rows):
            raise ImportRefused(
                f"this bundle writes {words}, which run on this machine; preview it and confirm "
                f"{section}.sha256 to import them", 409)


def run_import(
    config_path: Path,
    bundle: ConfigBundle,
    *,
    mode: Mode,
    dry_run: bool,
    pins: Dict[str, str],
    themes: Optional[Any],
    host: str,
    confirm_launch_profiles_sha256: Optional[str] = None,
    confirm_agents_sha256: Optional[str] = None,
    confirm_workspace_sha256: Optional[str] = None,
    confirm_browser_sha256: Optional[str] = None,
    confirm_provider_accounts_sha256: Optional[str] = None,
    confirm_common_slash_commands_sha256: Optional[str] = None,
    confirm_template_path_sha256: Optional[str] = None,
) -> tuple[Dict[str, Any], Optional[Built]]:
    prepared = prepare(bundle)
    summary = _summary(bundle, prepared, host)
    incoming_profiles = prepared.sections.get(LAUNCH_PROFILES_KEY)
    profiles_digest = bundle_guard.block_digest(incoming_profiles)

    if dry_run:
        doc = config_writer.read_config(config_path)
        built = build_document(doc, pins, prepared, mode)
        body = {"status": PREVIEW, "dry_run": True, "mode": mode, **summary, **built.preview}
        if profiles_digest:
            body["launch_profiles"] = {"sha256": profiles_digest, "profiles": bundle_guard.review(incoming_profiles)}
        written = _written_commands(doc, built)
        for section, key, _guard, _words in _COMMAND_GATES:
            if section in written:
                body[section] = {"sha256": command_guard.digest(written[section]), key: written[section]}
        if mode == "replace":
            body["kept"] = _kept_count(doc, prepared)
        body["contains_commands"] = bool(profiles_digest or written)
        return body, None

    if profiles_digest and confirm_launch_profiles_sha256 != profiles_digest:
        raise ImportRefused(
            "this bundle carries launch profiles, which can run shell; preview it and confirm "
            "launch_profiles.sha256 to import them", 409)

    captured: Dict[str, Built] = {}

    def mutate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        built = build_document(doc, pins, prepared, mode)
        _refuse_unconfirmed(_written_commands(doc, built), {
            "agents": confirm_agents_sha256,
            "workspace": confirm_workspace_sha256,
            "browser": confirm_browser_sha256,
            "provider_accounts": confirm_provider_accounts_sha256,
            "common_slash_commands": confirm_common_slash_commands_sha256,
            "template_path": confirm_template_path_sha256,
        })
        captured["built"] = built
        return built.document

    outcome = config_writer.commit(config_path, mutate, backup_required=True)
    if outcome.status == config_writer.BACKUP_UNAVAILABLE:
        raise ImportRefused("could not write a backup of the current config, so nothing was changed", 500)
    built = captured["built"]

    pins_changed = built.pins_after != clean_pins(pins)
    if pins_changed and themes is not None:
        themes.pinned_themes.clear()
        themes.pinned_themes.update(built.pins_after)
        themes.save()

    wrote = outcome.wrote or pins_changed
    logger.info(
        "config_import_applied",
        mode=mode,
        wrote_config=outcome.wrote,
        pins_changed=pins_changed,
        changes=built.preview["counts"],
        stripped=len(prepared.stripped),
    )
    body = {
        "status": APPLIED if wrote else UNCHANGED,
        "dry_run": False,
        "mode": mode,
        "backup": "config.json.bak" if outcome.wrote else None,
        **summary,
        **built.preview,
    }
    return body, (built if built.moved else None)
