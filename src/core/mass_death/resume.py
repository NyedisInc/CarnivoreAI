
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, List, Sequence

import structlog
from fastapi import HTTPException

from src.core.keymap.catalog_text import catalog_text

logger = structlog.get_logger()

NOTE_KEY = "session.mass_death.note"
MAX_SESSIONS: int = 50
WAKE_CONCURRENCY: int = 3


@dataclass(frozen=True)
class SessionOutcome:

    session_uuid: str
    status: str
    detail: str = ""


@dataclass
class ResumeReport:

    outcomes: List[SessionOutcome] = field(default_factory=list)

    @property
    def woken(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "woken")

    @property
    def refused(self) -> int:
        return len(self.outcomes) - self.woken


def note_text() -> str:
    return catalog_text(NOTE_KEY)


async def _wake(app_state: Any, session_uuid: str) -> Any:
    from src.api.session_sleep_routes import wake_by_uuid

    return await wake_by_uuid(app_state, session_uuid)


def _schedule_note(app_state: Any, tmux_name: str, text: str) -> None:
    from src.core.account_switch import resume_after_restart

    resume_after_restart.schedule_text(app_state, tmux_name, text)


async def _resume_one(app_state: Any, session_uuid: str, text: str, gate: asyncio.Semaphore) -> SessionOutcome:
    async with gate:
        try:
            answer = await _wake(app_state, session_uuid)
        except HTTPException as exc:
            logger.info("mass_death_wake_refused", session_uuid=session_uuid, status_code=exc.status_code)
            return SessionOutcome(session_uuid, "refused", str(exc.detail))
    if answer.status != "started" or not answer.tmux_session:
        return SessionOutcome(session_uuid, "refused", str(getattr(answer, "code", None) or answer.status))
    _schedule_note(app_state, answer.tmux_session, text)
    return SessionOutcome(session_uuid, "woken")


async def resume_all(app_state: Any, session_uuids: Sequence[str]) -> ResumeReport:
    distinct = list(dict.fromkeys(session_uuids))
    if len(distinct) > MAX_SESSIONS:
        raise ValueError(f"at most {MAX_SESSIONS} sessions per resume")
    gate = asyncio.Semaphore(WAKE_CONCURRENCY)
    text = note_text()
    outcomes = await asyncio.gather(*(_resume_one(app_state, uuid, text, gate) for uuid in distinct))
    report = ResumeReport(list(outcomes))
    logger.info("mass_death_resumed", woken=report.woken, refused=report.refused)
    return report
