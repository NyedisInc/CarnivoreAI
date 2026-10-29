
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import config_writer
from src.core.launch_profiles import bundle_guard
from src.core.config_bundle.bundle import ConfigBundle, clean_pins
from src.config.launch_profiles import LAUNCH_PROFILES_KEY
from src.core.config_bundle.importer import Built, ImportRefused, Mode, Prepared, build_document, prepare

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
) -> tuple[Dict[str, Any], Optional[Built]]:
    prepared = prepare(bundle)
    summary = _summary(bundle, prepared, host)
    incoming_profiles = prepared.sections.get(LAUNCH_PROFILES_KEY)
    profiles_digest = bundle_guard.block_digest(incoming_profiles)

    if dry_run:
        built = build_document(config_writer.read_config(config_path), pins, prepared, mode)
        body = {"status": PREVIEW, "dry_run": True, "mode": mode, **summary, **built.preview}
        if profiles_digest:
            body["launch_profiles"] = {"sha256": profiles_digest, "profiles": bundle_guard.review(incoming_profiles)}
        return body, None

    if profiles_digest and confirm_launch_profiles_sha256 != profiles_digest:
        raise ImportRefused(
            "this bundle carries launch profiles, which can run shell; preview it and confirm "
            "launch_profiles.sha256 to import them", 409)

    captured: Dict[str, Built] = {}

    def mutate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        built = build_document(doc, pins, prepared, mode)
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
