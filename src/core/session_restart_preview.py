
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

WRAPPERS_UNAVAILABLE: str = "unavailable"


@dataclass(frozen=True)
class WrapperOffer:

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
