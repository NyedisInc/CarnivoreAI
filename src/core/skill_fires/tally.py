
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.attention.evidence import FAMILY_CLAUDE, FAMILY_CODEX
from src.core.skill_fires.parse import HARNESS_CLAUDE, HARNESS_CODEX
from src.core.skill_fires.scan import (
    STATE_UNREADABLE, profile_for_path, scan_file,
)
from src.core.skill_fires.store import DB_NAME, SkillFireStore

logger = structlog.get_logger(__name__)

STATE_MEASURED = "measured"
STATE_NOT_MEASURED = "not_measured"
STATE_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SkillTally:

    state: str
    fired: Optional[int] = None
    last_skill: Optional[str] = None
    last_at: Optional[str] = None
    tripwire: tuple = ()


UNSUPPORTED = SkillTally(STATE_UNSUPPORTED)
NOT_MEASURED = SkillTally(STATE_NOT_MEASURED)


def default_store() -> SkillFireStore:
    from src.config import settings  # noqa: PLC0415
    return SkillFireStore(Path(settings.get_state_dir()) / DB_NAME)


class SkillTallyCache:

    def __init__(self, *, store: Optional[SkillFireStore] = None,
                 home: Optional[Path] = None) -> None:
        self._store = store
        self._home = home or Path.home()
        self._probe: Optional[Any] = None

    def set_probe(self, probe: Optional[Any]) -> None:
        self._probe = probe

    def tally(self, family: Optional[str], transcript_path: Optional[Any]) -> SkillTally:
        if family is not None and family not in (FAMILY_CLAUDE, FAMILY_CODEX):
            return UNSUPPORTED
        if transcript_path is None:
            return NOT_MEASURED
        path = os.path.realpath(str(transcript_path))
        harness = HARNESS_CODEX if family == FAMILY_CODEX else HARNESS_CLAUDE
        try:
            if self._store is None:
                self._store = default_store()
            result = scan_file(self._store, path, harness, profile_for_path(path, self._home))
            if result.state == STATE_UNREADABLE:
                return NOT_MEASURED
            latest = self._store.recent(path, limit=1)
            findings = self._probe.scan(path, harness) if self._probe is not None else ()
            return SkillTally(
                STATE_MEASURED, self._store.count(path),
                latest[0].skill if latest else None,
                latest[0].fired_at if latest else None, findings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill_tally_failed", error_type=type(exc).__name__)
            return NOT_MEASURED
