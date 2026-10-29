
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional

CONVERSATION_RESUMED: str = "resumed"

CONVERSATION_NONE_RECORDED: str = "none_recorded"

CONVERSATION_UNKNOWN: str = "unknown"

ALL_CONVERSATION_OUTCOMES: frozenset[str] = frozenset(
    {CONVERSATION_RESUMED, CONVERSATION_NONE_RECORDED, CONVERSATION_UNKNOWN}
)

_CONTINUE_TOKENS: tuple[str, ...] = ("--continue",)


@dataclass(frozen=True)
class ResumeTarget:

    outcome: str
    claude_session_uuid: Optional[str] = None
    detail: str = ""
    family: Optional[str] = None
    title: Optional[str] = None


def resume_target_from_row(
    row: Optional[Mapping[str, Any]], *, row_read_ok: bool
) -> ResumeTarget:
    if not row_read_ok:
        return ResumeTarget(
            outcome=CONVERSATION_UNKNOWN,
            detail=continuity_phrase(CONVERSATION_UNKNOWN),
        )
    uuid = ""
    family: Optional[str] = None
    title: Optional[str] = None
    if row is not None:
        raw = row.get("claude_session_uuid")
        uuid = str(raw).strip() if raw else ""
        fam = row.get("agent_family")
        family = str(fam).strip() if fam else None
        raw_title = row.get("title")
        title = str(raw_title).strip() if raw_title else None
    if not uuid:
        return ResumeTarget(
            outcome=CONVERSATION_NONE_RECORDED,
            detail=continuity_phrase(CONVERSATION_NONE_RECORDED),
            family=family,
            title=title,
        )
    return ResumeTarget(
        outcome=CONVERSATION_RESUMED,
        claude_session_uuid=uuid,
        detail=continuity_phrase(CONVERSATION_RESUMED),
        family=family,
        title=title,
    )


def upgrade_codex_adopted_target(
    target: ResumeTarget,
    *,
    working_dir: Optional[str],
    pick: Callable[[str], Optional[str]],
) -> ResumeTarget:
    from src.core.attention.evidence import FAMILY_CODEX

    if target.outcome != CONVERSATION_NONE_RECORDED:
        return target
    if target.family != FAMILY_CODEX:
        return target
    if not working_dir:
        return target
    picked = pick(working_dir)
    if not picked:
        return target
    return ResumeTarget(
        outcome=CONVERSATION_RESUMED,
        claude_session_uuid=str(picked).strip(),
        detail=continuity_phrase(CONVERSATION_RESUMED),
        family=FAMILY_CODEX,
        title=target.title,
    )


def resume_extra_args(target: Optional[ResumeTarget]) -> Optional[List[str]]:
    from src.core.session_restart import resume_arguments

    if target is None or target.outcome != CONVERSATION_RESUMED:
        return None
    if not target.claude_session_uuid:
        return None
    args = resume_arguments(target.claude_session_uuid, family=target.family)
    return args + _name_args_for_resume(target)


def _name_args_for_resume(target: ResumeTarget) -> List[str]:
    from src.core.claude_rename import RENAME_CAPABLE_FAMILY, name_is_pushable

    if target.family not in (None, RENAME_CAPABLE_FAMILY):
        return []
    title = (target.title or "").strip()
    if not title or not name_is_pushable(title):
        return []
    return ["--name", title]


def continuity_phrase(outcome: Optional[str]) -> str:
    if outcome == CONVERSATION_RESUMED:
        return "resuming the same conversation"
    if outcome == CONVERSATION_NONE_RECORDED:
        return (
            "no conversation is recorded for it, so it comes back "
            "without its history"
        )
    return "whether it resumes its conversation cannot be determined"


def continuity_from_command(command: Optional[str]) -> str:
    from src.core.session_respawn import resume_uuid_in

    if command is None:
        return CONVERSATION_UNKNOWN
    if resume_uuid_in(command):
        return CONVERSATION_RESUMED
    lowered = f"{command.strip()} "
    if any(token in lowered for token in _CONTINUE_TOKENS):
        return CONVERSATION_UNKNOWN
    return CONVERSATION_NONE_RECORDED
