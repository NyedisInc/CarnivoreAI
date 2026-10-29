
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

import structlog

from src.core.attention.evidence import FAMILY_CODEX
from src.core.claude_project_dirs import path_spellings
from src.core.claude_transcript_correlate import (
    default_projects_dir,
    slugify_project_dir,
)
from src.core.session_respawn import (
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_TRANSCRIPT_MISSING,
    RespawnPlan,
)
from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
    continuity_from_command,
    resume_extra_args,
    resume_target_from_row,
)

logger = structlog.get_logger()

DIRECTORY_MEASURED: str = "measured"

DIRECTORY_NOT_FOUND: str = "not_found"

DIRECTORY_UNCHECKED: str = "unchecked"


@dataclass(frozen=True)
class ResumeDirectory:

    outcome: str
    working_dir: Optional[str] = None
    transcript_path: Optional[str] = None
    checked: Sequence[str] = ()
    detail: str = ""

    @property
    def refuses(self) -> bool:
        return self.outcome == DIRECTORY_NOT_FOUND


def _codex_resume_directory(
    working_dir: str, thread_uuid: str
) -> ResumeDirectory:
    from src.core.session_transcript_presence import (
        CONVERSATION_PRESENT,
        family_conversation_presence,
    )

    presence = family_conversation_presence(FAMILY_CODEX, thread_uuid)
    if presence.outcome == CONVERSATION_PRESENT:
        return ResumeDirectory(
            outcome=DIRECTORY_MEASURED,
            working_dir=working_dir,
            transcript_path=str(presence.path),
            checked=(working_dir,),
            detail=(
                "the codex conversation's rollout is on disk, so the "
                "restart resumes it in the session's own directory"
            ),
        )
    return ResumeDirectory(
        outcome=DIRECTORY_NOT_FOUND if presence.missing else DIRECTORY_UNCHECKED,
        detail=presence.detail,
    )


def resume_directory(
    working_dir: Optional[str],
    claude_session_uuid: Optional[str],
    *,
    corpus_root: Optional[Path] = None,
    family: Optional[str] = None,
) -> ResumeDirectory:
    if not working_dir or not claude_session_uuid:
        return ResumeDirectory(
            outcome=DIRECTORY_UNCHECKED,
            detail=(
                "no working directory or no conversation id was given, so "
                "which directory a resume would run in was not evaluated"
            ),
        )
    if family == FAMILY_CODEX:
        return _codex_resume_directory(working_dir, claude_session_uuid)
    if corpus_root is not None:
        bases: Sequence[Path] = (corpus_root,)
    else:
        from src.core.claude_config.profile_roots import PROJECTS_DIRNAME, profile_subdir_roots

        bases = profile_subdir_roots(default_projects_dir(), PROJECTS_DIRNAME)
    spellings = path_spellings(working_dir)
    checked: List[str] = []
    for spelling in spellings:
        checked.append(spelling)
        for base in bases:
            candidate = base / slugify_project_dir(spelling) / f"{claude_session_uuid}.jsonl"
            try:
                if candidate.is_file():
                    return ResumeDirectory(
                        outcome=DIRECTORY_MEASURED,
                        working_dir=spelling,
                        transcript_path=str(candidate),
                        checked=tuple(checked),
                        detail=(
                            f"the conversation's transcript is filed under the "
                            f"spelling {spelling!r}, so the restart runs there"
                        ),
                    )
            except OSError as exc:
                logger.debug(
                    "imported_resume_dir_stat_failed",
                    candidate=str(candidate),
                    error=str(exc),
                )
                return ResumeDirectory(
                    outcome=DIRECTORY_UNCHECKED,
                    checked=tuple(checked),
                    detail=(
                        "the transcript corpus could not be read, so where this "
                        "conversation would resume from was not evaluated"
                    ),
                )
    if not checked:
        return ResumeDirectory(
            outcome=DIRECTORY_UNCHECKED,
            detail=(
                "no spelling of the working directory could be derived, so "
                "nothing was looked for"
            ),
        )
    return ResumeDirectory(
        outcome=DIRECTORY_NOT_FOUND,
        checked=tuple(checked),
        detail=(
            f"no transcript for this conversation is filed under any of the "
            f"{len(checked)} spelling(s) of its working directory, so a "
            "resume would exit immediately and leave an empty session"
        ),
    )


@dataclass(frozen=True)
class ImportedRestartPlan:

    kind: str
    command: Optional[str] = None
    conversation: str = CONVERSATION_UNKNOWN
    working_dir: Optional[str] = None
    reuse_session_id: Optional[int] = None
    label: Optional[str] = None
    agent_type: Optional[str] = None
    detail: str = ""

    @property
    def actionable(self) -> bool:
        return self.kind == RESPAWN_AGENT and bool(self.command)


def is_imported_row(row: Optional[Mapping[str, Any]]) -> bool:
    if row is None:
        return False
    return not row.get("tmux_name") and row.get("tmux_created_epoch") is None


def plan_imported_restart(
    row: Optional[Mapping[str, Any]],
    *,
    row_read_ok: bool,
    choice_verdict: Optional[str],
    choice_command: Optional[str],
    choice_detail: str = "",
    agent_type: Optional[str] = None,
    directory: Optional[ResumeDirectory] = None,
) -> ImportedRestartPlan:
    if not row_read_ok or row is None:
        return ImportedRestartPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            conversation=CONVERSATION_UNKNOWN,
            detail=(
                "the session's row could not be read, so what a restart "
                "would come back as was not evaluated"
            ),
        )

    target = resume_target_from_row(row, row_read_ok=True)
    measured = directory or ResumeDirectory(
        outcome=DIRECTORY_UNCHECKED,
        detail="where this conversation would resume from was not evaluated",
    )
    if measured.refuses:
        return ImportedRestartPlan(
            kind=RESPAWN_TRANSCRIPT_MISSING,
            conversation=target.outcome,
            reuse_session_id=_row_id(row),
            detail=measured.detail,
        )

    if choice_verdict != "accepted" or not choice_command:
        return ImportedRestartPlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            conversation=target.outcome,
            reuse_session_id=_row_id(row),
            agent_type=agent_type,
            detail=(
                choice_detail
                or "no launch wrapper was resolved, so there is nothing to run"
            ),
        )

    conversation = continuity_from_command(choice_command)
    working_dir = measured.working_dir or _str(row.get("working_dir"))
    title = _str(row.get("title")) or _str(row.get("claude_title"))
    return ImportedRestartPlan(
        kind=RESPAWN_AGENT,
        command=choice_command,
        conversation=conversation,
        working_dir=working_dir,
        reuse_session_id=_row_id(row),
        label=title,
        agent_type=agent_type,
        detail=(
            f"this conversation has no tmux session, so a restart creates "
            f"one in {working_dir!r} running the wrapper you picked, "
            + (
                "on the same conversation"
                if conversation == CONVERSATION_RESUMED
                else "and "
                + (
                    "WITHOUT its history, because no conversation is "
                    "recorded on this row"
                    if conversation == CONVERSATION_NONE_RECORDED
                    else "nothing claims to resume its history, because "
                    "the conversation could not be determined"
                )
            )
        ),
    )


def imported_extra_args(row: Optional[Mapping[str, Any]], *, row_read_ok: bool):
    from src.core.swarm.launch import with_swarm_args

    return with_swarm_args(
        row.get("id") if row else None, resume_extra_args(resume_target_from_row(row, row_read_ok=row_read_ok))
    )


def _row_id(row: Mapping[str, Any]) -> Optional[int]:
    value = row.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_respawn_plan(plan: ImportedRestartPlan) -> RespawnPlan:
    return RespawnPlan(
        kind=plan.kind,
        command=plan.command,
        detail=plan.detail,
        chosen=bool(plan.agent_type),
        conversation=plan.conversation,
        kills_live_pane=False,
    )
