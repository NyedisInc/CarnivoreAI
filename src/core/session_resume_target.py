
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional

CONVERSATION_RESUMED: str = "resumed"

# without its history
CONVERSATION_NONE_RECORDED: str = "none_recorded"

# could not be read
# cannot be determined
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
    """The argv fragment that makes a restart resume its conversation.

    Description: the ONE place a restart's ``--resume`` is built, so the
        preview and the action cannot render different commands. Handed
        to ``Settings.get_agent_command(extra_args=...)``, which quotes
        each element at every shell boundary it crosses and threads them
        through the user's own wrapper. Never concatenated onto a
        resolved command string - see the module docstring for why that
        would put the flag outside the wrapper's quoting.

        The argument list itself comes from
        ``session_restart.resume_arguments`` rather than being spelled a
        second time here.

    Inputs:
        target: the resolved conversation, or None when none was
            resolved.

        A claude resume also carries ``--name <title>`` when
        ``target.title`` is set and pushable (see
        :func:`_name_args_for_resume`), so the restarted pane comes back
        wearing the same name claude itself would show, rather than
        reverting to whatever claude last had on file for that
        conversation. Codex never gets this: its CLI has no ``--name``,
        and appending one there would hand codex an argument it does not
        recognise.

    Inputs:
        target: the resolved conversation, or None when none was
            resolved.

    Output:
        Optional[list[str]]: ``['--resume', '<uuid>']``, extended with
            ``['--name', '<title>']`` for a claude row with a pushable
            title; or ``['resume', '<uuid>']`` for codex (the subcommand
            form, never extended with ``--name``); or None when there is
            no conversation to resume or the row could not be read. None
            means "add nothing", never "resume something".

    Example:
        >>> resume_extra_args(ResumeTarget(CONVERSATION_RESUMED, 'abc'))
        ['--resume', 'abc']
        >>> resume_extra_args(
        ...     ResumeTarget(CONVERSATION_RESUMED, 'abc', title='Spike'))
        ['--resume', 'abc', '--name', 'Spike']
        >>> resume_extra_args(None) is None
        True
    """
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
