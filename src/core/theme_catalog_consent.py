
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog

from src.core import theme_script_consent, theme_script_digest
from src.core.ui_preferences_store import COMMITTED, STALE_REVISION

logger = structlog.get_logger()

CONSENT_FIELD = "theme_script_consent"


def effects_digest_of(theme_dir: Path) -> Optional[str]:
    manifest_path = theme_dir / "theme.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "theme_catalog_manifest_unreadable",
            path=str(manifest_path),
            error=str(exc),
        )
        return None
    if not isinstance(raw, dict):
        return None
    return theme_script_digest.digest_effects(theme_dir, raw.get("effects"))


def stale_grant(
    record: Optional[Mapping[str, Any]], effects_digest: Optional[str]
) -> bool:
    if not isinstance(record, Mapping):
        return False
    if record.get("decision") != theme_script_consent.DECISION_ALWAYS:
        return False
    granted = record.get("digest")
    if not isinstance(granted, str) or not theme_script_consent.DIGEST_RE.match(
        granted
    ):
        return False
    return granted != effects_digest


def drop_stale_effects_grant(store: Any, theme_id: str, theme_dir: Path) -> bool:
    if not theme_script_consent.is_keyable_theme_id(theme_id):
        return False

    result = None
    try:
        for _attempt in range(2):
            block = store.read()
            current = (block.get("values") or {}).get(CONSENT_FIELD) or {}
            if not isinstance(current, dict):
                return False

            entry = current.get(theme_id)
            if not stale_grant(entry, effects_digest_of(theme_dir)):
                return False

            remaining = {key: value for key, value in current.items() if key != theme_id}
            result = store.update(
                {CONSENT_FIELD: remaining or None}, expected_revision=block.get("revision")
            )
            if getattr(result, "status", None) != STALE_REVISION:
                break
    except (OSError, ValueError) as exc:
        logger.warning(
            "theme_script_grant_drop_failed",
            theme_id=theme_id,
            error=str(exc),
        )
        return False

    status = getattr(result, "status", None)
    if status != COMMITTED:
        logger.warning("theme_script_grant_drop_not_committed", theme_id=theme_id, status=status)
        return False

    logger.info(
        "theme_script_grant_dropped",
        theme_id=theme_id,
        status=status,
        reason="the catalog wrote a different effects.js than the one granted",
    )
    return True
