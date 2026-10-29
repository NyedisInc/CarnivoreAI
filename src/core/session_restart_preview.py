"""What a restart WOULD do, answered without doing it.

THE GAP THIS CLOSES. Until now ``POST /sessions/respawn`` was the only
entry into the respawn ladder and it MUTATES, so there was no way to ask
which rung a session would land on before committing to it. That made an
honest warning impossible, and the warning is the part that matters:
an empty ``#{pane_start_command}`` lands on ``RESPAWN_SHELL``, which
hands back a LOGIN SHELL. A picker that lets someone confidently choose
``claude-chrome`` and then drops them at a zsh prompt is worse than no
picker at all.

SO THE PREVIEW RUNS THE SAME FUNCTION THE ACTION RUNS. Every outcome
below comes out of ``resolve_respawn_plan`` in
``src/core/session_respawn.py``, called with the same probe values the
respawn would use. It is not a second model of the ladder and it cannot
drift from one, because there is only one ladder. What this module adds
is the SHAPE: run it once with no override to get "what a plain restart
does", then once per configured wrapper to get "what picking this one
does", and hand the caller both.

So every plan here is produced TWICE, from the same single probe:

``pane_state`` carries the liveness fact on its own ('dead' / 'alive' /
'unknown') so the two can never be read as one.

ONE ROUND TRIP, ON PURPOSE. The alternative - re-asking the server every
time the highlighted wrapper changes - would put a network hop inside a
radio-button click and would let the panel show a stale verdict next to
a fresh selection. The pane is probed once and every option is derived
from that single reading, so the options on screen are all answers about
the same observed state.

THE THIRD OUTCOME APPEARS TWICE HERE, and neither instance may be
flattened into a zero:

  ``wrappers_status``  'ok' means the wrapper list was read and
                       ``options`` reflects it; an EMPTY options list
                       then genuinely means this install configures no
                       wrappers. 'unavailable' means the list could not
                       be read, and a client that draws that as "no
                       wrappers to pick" is stating something nobody
                       measured.
  each option's ``kind``
                       carries ``cannot_determine`` on its own terms.
                       An option whose command could not be resolved is
                       reported unavailable WITH its reason, never
                       silently dropped from the list - a choice that
                       vanishes looks like a choice that never existed.

WHAT IT DOES NOT DO. It performs no I/O of any kind: the caller probes
tmux, reads the row and resolves the wrapper commands, and this
classifies. Same division of labour as the ladder itself, and the same
reason - it makes every outcome testable without a tmux binary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.session_resume_target import CONVERSATION_UNKNOWN
from src.core.session_respawn import (
    RESPAWN_CANNOT_DETERMINE,
    RespawnPlan,
    pane_state_from_probe,
    project_restart_rung,
    refuse_if_transcript_missing,
    resolve_respawn_plan,
)

WRAPPERS_OK: str = "ok"

# could not be read
# could not
WRAPPERS_UNAVAILABLE: str = "unavailable"


@dataclass(frozen=True)
class WrapperOffer:
    """One configured wrapper, as the caller resolved it.

    Attributes:
        agent_type: the wrapper id, which doubles as ``agent_type``.
        label: display name, falling back to the id.
        command: shell string this wrapper renders to, or None when it
            could not be resolved.
        unavailable_reason: why ``command`` is None. Required whenever it
            is, so the option can be shown greyed out with a reason
            instead of disappearing.
        family: the wrapper's agent family, for its mark; "" unknown.
        icon: the wrapper's chosen icon id, or None for the family mark
            (issue #1004).
    """

    agent_type: str
    label: str = ""
    command: Optional[str] = None
    unavailable_reason: str = ""
    family: str = ""
    icon: Optional[str] = None


@dataclass(frozen=True)
class PreviewOption:

    agent_type: str
    label: str
    is_current: bool
    resolvable: bool
    actionable_now: bool
    kind: str
    detail: str
    projected_kind: str = ""
    projected_detail: str = ""
    command: Optional[str] = None
    family: str = ""
    icon: Optional[str] = None
    conversation: str = ""
    same_as_unchanged: bool = False


@dataclass(frozen=True)
class RestartPreview:

    name: str
    current_agent_type: Optional[str]
    pane_state: str
    unchanged: RespawnPlan
    projected: RespawnPlan
    options: List[PreviewOption]
    wrappers_status: str
    launch_display: Optional[Dict[str, object]] = None


def _mark_same_launch(
    option: PreviewOption, baseline_command: Optional[str]
) -> PreviewOption:
    base = (baseline_command or "").strip()
    mine = (option.command or "").strip()
    if option.is_current and base and mine == base:
        return replace(option, same_as_unchanged=True)
    return option


def build_restart_preview(
    *,
    name: str,
    probe_ok: bool,
    pane_dead: Optional[str],
    pane_start_command: Optional[str],
    stored_agent_type: Optional[str],
    stored_agent_command: Optional[str],
    offers: Optional[Sequence[WrapperOffer]],
    presence_outcome: Optional[str] = None,
    presence_detail: str = "",
    presence_by_uuid: Optional[Mapping[str, Tuple[Optional[str], str]]] = None,
    resume_outcome: Optional[str] = None,
) -> RestartPreview:
    """Predict every restart outcome for one pane, changing nothing.

    Description: runs the ladder once with no override and once per
        offered wrapper, all against the same single reading of the pane.
        Pure - see the module docstring.

    Inputs:
        name: tmux session name, echoed back so a response identifies
            itself.
        probe_ok: True iff the tmux pane query answered.
        pane_dead: raw ``#{pane_dead}`` ("0" / "1"), or None.
        pane_start_command: raw ``#{pane_start_command}``. Empty string
            means tmux positively recorded none; None means the field was
            not returned.
        stored_agent_type: ``sessions.agent_type`` for this session, or
            None.
        stored_agent_command: what that stored type resolves to now, or
            None when the app has no record.
        offers: the configured wrappers, already resolved. None means the
            list could not be read, which is reported as
            ``WRAPPERS_UNAVAILABLE`` and is NOT the same as ``[]``.
        presence_outcome: ``'present'`` / ``'absent'`` / ``'unchecked'``
            for the conversation the RECORDED start command would resume,
            or None when nothing would be resumed. The caller does the
            filesystem lookup; this only classifies.

    Output:
        RestartPreview.

    Example:
        >>> p = build_restart_preview(name='cloude_api', probe_ok=True,
        ...     pane_dead='1', pane_start_command='', stored_agent_type=None,
        ...     stored_agent_command=None, offers=[])
        >>> p.unchanged.kind, p.pane_state
        ('shell', 'dead')
        >>> live = build_restart_preview(name='cloude_api', probe_ok=True,
        ...     pane_dead='0', pane_start_command='', stored_agent_type=None,
        ...     stored_agent_command=None, offers=[])
        >>> live.unchanged.kind, live.projected.kind
        ('not_dead', 'shell')
    """
    def _guard(plan: RespawnPlan) -> RespawnPlan:
        if presence_by_uuid is None:
            return refuse_if_transcript_missing(
                plan, presence_outcome, presence_detail
            )
        found = presence_by_uuid.get(plan.resume_uuid or "")
        if found is None:
            return plan
        return refuse_if_transcript_missing(plan, found[0], found[1])

    unchanged = _guard(resolve_respawn_plan(
        probe_ok=probe_ok,
        pane_dead=pane_dead,
        pane_start_command=pane_start_command,
        agent_command=stored_agent_command,
        resume_outcome=resume_outcome,
    ))
    projected = _guard(project_restart_rung(
        probe_ok=probe_ok,
        pane_start_command=pane_start_command,
        agent_command=stored_agent_command,
        resume_outcome=resume_outcome,
    ))
    pane_state = pane_state_from_probe(probe_ok, pane_dead)

    if offers is None:
        return RestartPreview(
            name=name,
            current_agent_type=stored_agent_type,
            pane_state=pane_state,
            unchanged=unchanged,
            projected=projected,
            options=[],
            wrappers_status=WRAPPERS_UNAVAILABLE,
        )

    options: List[PreviewOption] = []
    for offer in offers:
        label = offer.label or offer.agent_type
        is_current = bool(
            stored_agent_type and stored_agent_type == offer.agent_type
        )
        if not (offer.command or "").strip():
            reason = (
                offer.unavailable_reason
                or f"'{offer.agent_type}' could not be turned into a command"
            )
            options.append(
                PreviewOption(
                    agent_type=offer.agent_type,
                    label=label,
                    family=offer.family,
                    icon=offer.icon,
                    is_current=is_current,
                    resolvable=False,
                    actionable_now=False,
                    kind=RESPAWN_CANNOT_DETERMINE,
                    detail=reason,
                    projected_kind=RESPAWN_CANNOT_DETERMINE,
                    projected_detail=reason,
                    command=None,
                    conversation=CONVERSATION_UNKNOWN,
                )
            )
            continue

        plan = _guard(resolve_respawn_plan(
            probe_ok=probe_ok,
            pane_dead=pane_dead,
            pane_start_command=pane_start_command,
            agent_command=stored_agent_command,
            chosen_agent_command=offer.command,
            chosen_agent_type=offer.agent_type,
            resume_outcome=resume_outcome,
        ))
        option_projected = _guard(project_restart_rung(
            probe_ok=probe_ok,
            pane_start_command=pane_start_command,
            agent_command=stored_agent_command,
            chosen_agent_command=offer.command,
            chosen_agent_type=offer.agent_type,
            resume_outcome=resume_outcome,
        ))
        options.append(
            PreviewOption(
                agent_type=offer.agent_type,
                label=label,
                family=offer.family,
                icon=offer.icon,
                is_current=is_current,
                resolvable=True,
                actionable_now=plan.actionable,
                kind=plan.kind,
                detail=plan.detail,
                projected_kind=option_projected.kind,
                projected_detail=option_projected.detail,
                command=option_projected.command,
                conversation=option_projected.conversation,
            )
        )

    options = [_mark_same_launch(o, projected.command) for o in options]
    return RestartPreview(
        name=name,
        current_agent_type=stored_agent_type,
        pane_state=pane_state,
        unchanged=unchanged,
        projected=projected,
        options=options,
        wrappers_status=WRAPPERS_OK,
    )
