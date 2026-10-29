"""Bringing back a session whose tmux SESSION is gone, on the row it has.

THE GAP THIS CLOSES, AND WHY IT IS NOT ANY OF THE THREE PATHS THAT
ALREADY EXIST. ``POST /sessions/respawn`` puts a process back into a pane
that is still THERE - ``remain-on-exit on`` kept the window, the pane id
and the ``pipe-pane`` alive, so there is something to respawn into.
``respawn-pane -k`` replaces the process in a pane that is alive. And
``src/core/session_imported_restart.py`` creates a session for a row that
never had a tmux identity at all.

None of them can reach the case in between: a row that DID have a tmux
session and no longer does. The tmux server was restarted, the session
was killed outright, the machine rebooted - the name is simply absent
from ``tmux -L cloude list-sessions``. There is no pane to respawn into,
so the respawn ladder reads the pane, gets nothing, and answers
``cannot_determine``: an honest refusal that leaves the user with one
option, which is to build a fresh session by hand and lose the row. The
row is where the project binding, the title, the pinned theme, the unread
key and the group membership live, so losing it loses all five.

SO THE MECHANIC IS A CREATE AND THE SEMANTIC IS STILL A RESUME. CLAUDE.md
states the rule: "A RESTART MEANS A RESUME, ON EVERY RUNG THAT CAN". This
is that rule applied to the one rung that could not: a new tmux session,
in the conversation's own directory, under the wrapper the user picked,
with ``--resume <uuid>``, recorded ONTO the existing row through
``create_session(reuse_session_id=...)`` so nothing is minted beside it.

NOTHING NEW IS INVENTED TO DECIDE IT. The transcript guard, the directory
measurement, the wrapper validation, the ``--resume`` fragment and the
three conversation words are all the imported path's, imported rather
than respelled: :func:`plan_recreate` measures the one fact only it has -
whether the tmux session is still on the socket - and hands everything
else to ``plan_imported_restart``. A second spelling of any of those
rules would eventually disagree with the pane path, and the disagreement
would be invisible until it refused a restart somebody needed.

  :data:`TMUX_GONE`     the listing ran, was COMPLETE, and the name is
        not in it. The only outcome a recreate may be offered on.
  :data:`TMUX_PRESENT`  the name is in the listing. The existing restart
        owns this session; a recreate would spawn a second tmux beside a
        live one and rebind the row onto the newcomer, orphaning the pane
        the user is actually talking to. Reported as ``not_dead``, the
        same word the respawn ladder uses for the same refusal.
  :data:`TMUX_UNKNOWN`  the listing did not run, or ran with rows the
        parser refused, or the name is one this listing cannot see. NOT
        gone. Not having been able to look is not evidence of absence,
        and this is the gate on an action that writes a row.

A NAME OUTSIDE THE ``cloude_`` NAMESPACE IS ALWAYS UNKNOWN.
``discover_existing`` filters to ``SESSION_PREFIX``, so a session named
anything else is absent from that listing whether it is running or not,
and reading its absence as a measurement would be reading the filter
rather than the socket. An adopted external session therefore never
reaches the gate, which is also the right answer on its own terms: this
app did not launch it and has no record of what to put back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import structlog

from src.core.session_imported_restart import (
    ImportedRestartPlan,
    ResumeDirectory,
    plan_imported_restart,
)
from src.core.session_recreate_presence import (
    TMUX_GONE,
    TMUX_PRESENT,
    TMUX_UNKNOWN,
    TmuxPresence,
)
from src.core.session_respawn import (
    RESPAWN_AGENT,
    RESPAWN_CANNOT_DETERMINE,
    RESPAWN_NOT_DEAD,
    RespawnPlan,
)
from src.core.session_resume_target import (
    CONVERSATION_NONE_RECORDED,
    CONVERSATION_RESUMED,
    CONVERSATION_UNKNOWN,
)

logger = structlog.get_logger()

RECREATE: str = "recreate"


def has_tmux_identity(row: Optional[Mapping[str, Any]]) -> bool:
    from src.core.session_imported_restart import is_imported_row

    if row is None:
        return False
    return not is_imported_row(row)


@dataclass(frozen=True)
class RecreatePlan:

    kind: str
    command: Optional[str] = None
    conversation: str = CONVERSATION_UNKNOWN
    presence: str = TMUX_UNKNOWN
    working_dir: Optional[str] = None
    tmux_name: Optional[str] = None
    reuse_session_id: Optional[int] = None
    label: Optional[str] = None
    agent_type: Optional[str] = None
    detail: str = ""

    @property
    def actionable(self) -> bool:
        return self.kind == RECREATE and bool(self.command)


def plan_recreate(
    row: Optional[Mapping[str, Any]],
    *,
    row_read_ok: bool,
    presence: TmuxPresence,
    choice_verdict: Optional[str] = None,
    choice_command: Optional[str] = None,
    choice_detail: str = "",
    agent_type: Optional[str] = None,
    directory: Optional[ResumeDirectory] = None,
) -> RecreatePlan:
    if not row_read_ok or row is None:
        return RecreatePlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            presence=presence.outcome,
            detail=(
                "the session's row could not be read, so what recreating "
                "it would do was not evaluated"
            ),
        )

    tmux_name = _str(row.get("tmux_name"))

    if presence.outcome == TMUX_PRESENT:
        return RecreatePlan(
            kind=RESPAWN_NOT_DEAD,
            presence=presence.outcome,
            tmux_name=tmux_name,
            reuse_session_id=_row_id(row),
            detail=presence.detail,
        )

    if presence.outcome != TMUX_GONE:
        return RecreatePlan(
            kind=RESPAWN_CANNOT_DETERMINE,
            presence=presence.outcome,
            tmux_name=tmux_name,
            reuse_session_id=_row_id(row),
            detail=presence.detail
            or (
                "whether this session's tmux is still running could not "
                "be determined, so nothing was offered"
            ),
        )

    inner: ImportedRestartPlan = plan_imported_restart(
        row,
        row_read_ok=True,
        choice_verdict=choice_verdict,
        choice_command=choice_command,
        choice_detail=choice_detail,
        agent_type=agent_type,
        directory=directory,
    )

    if inner.kind != RESPAWN_AGENT:
        return RecreatePlan(
            kind=inner.kind,
            command=inner.command,
            conversation=inner.conversation,
            presence=presence.outcome,
            working_dir=inner.working_dir,
            tmux_name=tmux_name,
            reuse_session_id=inner.reuse_session_id or _row_id(row),
            label=inner.label,
            agent_type=agent_type,
            detail=inner.detail,
        )

    return RecreatePlan(
        kind=RECREATE,
        command=inner.command,
        conversation=inner.conversation,
        presence=presence.outcome,
        working_dir=inner.working_dir,
        tmux_name=tmux_name,
        reuse_session_id=inner.reuse_session_id,
        label=inner.label,
        agent_type=agent_type,
        detail=_recreate_sentence(inner.conversation, inner.working_dir),
    )


def _recreate_sentence(conversation: str, working_dir: Optional[str]) -> str:
    where = f" in {working_dir!r}" if working_dir else ""
    if conversation == CONVERSATION_RESUMED:
        tail = "on the same conversation"
    elif conversation == CONVERSATION_NONE_RECORDED:
        tail = (
            "WITHOUT its history, because no conversation is recorded on "
            "this row"
        )
    else:
        tail = (
            "and nothing claims to resume its history, because the "
            "conversation could not be determined"
        )
    return (
        f"this session's tmux is gone, so recreating it starts a new one"
        f"{where} on the same record, {tail}. its old scrollback does not "
        "come back."
    )


def as_respawn_plan(plan: RecreatePlan) -> RespawnPlan:
    return RespawnPlan(
        kind=plan.kind,
        command=plan.command,
        detail=plan.detail,
        chosen=bool(plan.agent_type),
        conversation=plan.conversation,
        kills_live_pane=False,
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
