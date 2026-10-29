
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog

from src.core import theme_script_consent, theme_script_digest

logger = structlog.get_logger()

CONSENT_FIELD = "theme_script_consent"


def effects_digest_of(theme_dir: Path) -> Optional[str]:
    """The digest a run-grant for this theme folder is keyed on, or None.

    Description: reads the folder's own ``theme.json`` to find out WHETHER
      a script is declared and WHICH file it is, then takes the digest of
      the WHOLE FOLDER, which is exactly what ``GET /themes`` does when it
      stamps ``effectsDigest``. Reading the manifest rather than assuming
      the name is what keeps the two in agreement: a theme may call its
      script anything, and ``digest_effects`` refuses a name carrying a
      path separator.

      THE VALUE IS THE FOLDER'S, NOT THE DECLARED FILE'S, because an
      ``effects.js`` may import its siblings; see
      :mod:`src.core.theme_script_digest` for the bypass that closes. Note
      the consequence here: an INSTALLED folder also carries the
      ``.carnivore-skill.json`` sidecar, whose ``installed_at`` moves on
      every write, so a catalog write to a theme always leaves the stored
      grant stale and always re-asks. That is correct rather than a gap -
      the folder genuinely changed.
    Inputs: theme_dir (Path) - an installed or staged theme folder.
    Output: str | None - 64 lowercase hex, or None when the theme
      declares no script, or its manifest could not be read, or the file
      could not be measured. THE THREE ARE ONE ANSWER HERE on purpose:
      every one of them means "no bytes I can name", and the only thing
      this module does with that is decline to match a grant against it.
    Example: effects_digest_of(Path("~/themes/neon"))
    """
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

    try:
        block = store.read()
        current = (block.get("values") or {}).get(CONSENT_FIELD) or {}
        if not isinstance(current, dict):
            return False

        entry = current.get(theme_id)
        if not stale_grant(entry, effects_digest_of(theme_dir)):
            return False

        remaining = {key: value for key, value in current.items() if key != theme_id}
        result = store.update({CONSENT_FIELD: remaining or None})
    except (OSError, ValueError) as exc:
        logger.warning(
            "theme_script_grant_drop_failed",
            theme_id=theme_id,
            error=str(exc),
        )
        return False

    logger.info(
        "theme_script_grant_dropped",
        theme_id=theme_id,
        status=getattr(result, "status", None),
        reason="the catalog wrote a different effects.js than the one granted",
    )
    return True
