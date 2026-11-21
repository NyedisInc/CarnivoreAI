
from __future__ import annotations

from typing import Any, Iterable, Optional

from src.core.attention.evidence import FAMILY_CODEX
from src.core.codex_helpers import alerts, runtime
from src.core.codex_helpers.check import HelperCheck
from src.models import SessionInfo
from src.models.session_marks import CodexHelpersMark


def mark_for(check: Optional[HelperCheck]) -> Optional[CodexHelpersMark]:
    if check is None:
        return None
    return CodexHelpersMark(verdict=check.verdict, version=check.version, text=alerts.row_text(check),
                            checked_at=check.checked_at.isoformat())


def check_for_row(info: Any) -> Optional[HelperCheck]:
    if getattr(info, "agent_family", None) != FAMILY_CODEX:
        return None
    update = getattr(info, "agent_update", None)
    running = getattr(update, "running", None) if update is not None else None
    if running:
        return runtime.for_version(running)
    return runtime.latest()


def mark_codex_helpers(infos: Iterable[Any]) -> None:
    for info in infos:
        if isinstance(info, SessionInfo):
            info.codex_helpers = mark_for(check_for_row(info))
