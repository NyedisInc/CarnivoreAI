
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional

import structlog

from src.cplugs.save.vault import location, retention
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.sdk import SettingsVerdict, SettingsWarning, transcript_files as tf, vault_health, vault_sources

logger = structlog.get_logger()

SAME_DISK_CODE = "same_disk_transcripts"
SAME_DISK_MESSAGE = "same disk as your transcripts"
LEFT_BEHIND_CODE = "vault_left_behind"


def transcripts_root() -> Optional[Path]:
    roots = vault_sources.claude_roots()
    return Path(roots[0]) if roots else None


def warnings_for(root: Path) -> List[SettingsWarning]:
    sentence = location.transcripts_disk_warning(root, transcripts_root())
    return [SettingsWarning(SAME_DISK_CODE, SAME_DISK_MESSAGE, vault_health.LOCATION_SETTING, sentence)] if sentence else []


def candidate_root(value: str, state_dir: Path) -> Path:
    return Path(value.strip()).expanduser() if value.strip() else Path(state_dir) / vault_health.DEFAULT_DIR_NAME


def check_settings(changes: Mapping[str, Any]) -> SettingsVerdict:
    if vault_health.LOCATION_SETTING not in changes:
        return SettingsVerdict()
    raw = changes[vault_health.LOCATION_SETTING]
    value = raw if isinstance(raw, str) else ""
    problems = location.refusals(value) if value.strip() else []
    if problems:
        return SettingsVerdict(refusal=problems[0])
    state = Path(tf.state_dir())
    candidate = candidate_root(value, state)
    try:
        location.ensure_root(candidate)
    except VaultUnavailable as exc:
        return SettingsVerdict(refusal=str(exc))
    advice = warnings_for(candidate)
    previous = location.resolve_root(state)
    if previous != candidate:
        try:
            left = retention.sole_copy_units(previous) if previous.is_dir() else 0
        except OSError as exc:
            logger.warning("save_old_vault_unreadable", root=str(previous), error=str(exc))
            left = 0
        if left:
            logger.warning("save_vault_moved_with_sole_copies_left", root=str(previous), conversations=left)
            advice.append(SettingsWarning(
                LEFT_BEHIND_CODE, f"the old vault holds the only copy of {left} conversation(s)", vault_health.LOCATION_SETTING,
                f"the vault folder left behind, {previous}, holds the only copy of {left} conversation(s) whose originals are "
                "gone; it is kept where it is and not read from the new location"))
    return SettingsVerdict(warnings=tuple(advice))
