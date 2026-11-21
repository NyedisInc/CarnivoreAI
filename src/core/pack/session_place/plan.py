
from __future__ import annotations

import dataclasses
import re
from typing import List, Mapping, Optional, Sequence, Tuple

from src.core.pack.jobs import install as install_mod, place
from src.core.pack.jobs.policy import Policy
from src.core.pack.machines import capabilities
from src.core.pack.placement import needs as needs_mod
from src.core.pack.placement.needs import Need
from src.core.pack.placement.workload import KIND_SESSION, resolve
from src.core.pack.session_place.types import CAP_SESSION_PLACE, FAMILIES, REASON_MAX, PlaceRequest, SessionPlacement

_AGENT_TOOL = {"claude": "claude", "codex": "codex"}


def clip(text: str, limit: int = REASON_MAX) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: object, limit: int = REASON_MAX) -> str:
    return clip(_CONTROL.sub(" ", str(text or "")).strip(), limit)


OTHER_FAMILY = "other"


def family_of(agent: Optional[str]) -> Tuple[str, Optional[str]]:
    agent = agent or "claude"
    if agent in FAMILIES:
        return agent, None
    from src.config import settings  # noqa: PLC0415

    for profile in settings.get_launch_profiles():
        if profile.id.lower() == agent.lower():
            return (profile.harness, agent) if profile.harness in FAMILIES else (OTHER_FAMILY, agent)
    return OTHER_FAMILY, agent


def owner_posture(agent: Optional[str]) -> str:
    from src.config import settings  # noqa: PLC0415
    from src.core.launch_profiles.resolve import LaunchRequest, pick_profile  # noqa: PLC0415

    profile = pick_profile(LaunchRequest(profiles=tuple(settings.get_launch_profiles()), agent_type=agent or "claude"))
    if profile.custom_command is not None or (profile.before_launch or "").strip():
        return "unknown"
    return "ask" if profile.permissions == "harness_default" else (profile.permissions if profile.permissions in ("ask", "accept_edits", "skip_all") else "unknown")


def request_for(agent: Optional[str], *, working_dir: Optional[str] = None, project: Optional[str] = None, needs: Sequence[str] = ()) -> PlaceRequest:
    family, profile_name = family_of(agent)
    return PlaceRequest(project=project, working_dir=working_dir, family=family, needs=list(needs), profile_name=profile_name)


def agent_filters(family: str) -> List[Need]:
    tool = _AGENT_TOOL.get(family)
    return [needs_mod.parse_need(tool)] if tool else []


def merge_needs(starter_words: Sequence[str], stored_words: Sequence[str]) -> List[Need]:
    return list(dict.fromkeys([*needs_mod.parse_all(list(starter_words)), *needs_mod.parse_all(list(stored_words))]))


def _here_reason(answer_reason: str, skipped: Sequence[str]) -> str:
    if not skipped or not answer_reason.startswith("no other computer can take it now ("):
        return answer_reason
    inner = answer_reason[len("no other computer can take it now ("):-1]
    inner = "" if inner == "none is paired" else inner
    return "no other computer can take it now (" + "; ".join([*skipped, *([inner] if inner else [])]) + ")"


def plan(req: PlaceRequest, policy: Policy, view: place.PlaceView, needs: Sequence[Need], copies: Optional[Mapping[str, str]] = None, *,
         filters: Sequence[Need] = (), prefer: Sequence[Need] = ()) -> SessionPlacement:
    copies = copies or {}
    if not policy.auto_delegate:
        return SessionPlacement("here", "project is set to this computer only", project_uid=policy.project_uid)
    if not view.self_input.is_home:
        return SessionPlacement("here", "this computer holds a copy, not the project's home", project_uid=policy.project_uid)
    skipped: List[str] = []
    kept = []
    for peer in view.peers:
        if not peer.label:
            skipped.append(f"{peer.install_id[:8]} has no name")
        elif not copies.get(peer.install_id):
            skipped.append(f"{peer.label} has no copy of this project")
        elif not capabilities.has(view.caps.get(peer.install_id), CAP_SESSION_PLACE):
            skipped.append(f"{peer.label} runs an older carnivore")
        else:
            kept.append(peer)
    caps = {iid: [c for c in names if c != install_mod.CAP_INSTALL] for iid, names in view.caps.items()}
    narrowed = dataclasses.replace(view, peers=kept, caps=caps)
    answer = place.place(resolve({"kind": KIND_SESSION}), policy.project_uid, policy, narrowed, needs=list(needs),
                         filters=[*filters, *agent_filters(req.family)], prefer=list(prefer))
    detail = answer.reason if not skipped else f"{answer.reason}; skipped: {'; '.join(skipped)}"
    if answer.decision == "remote" and answer.peer_install_id and not answer.install:
        return SessionPlacement("remote", clip(answer.reason), answer.peer_install_id, answer.peer_label, copies[answer.peer_install_id],
                                candidates=list(answer.why), detail=detail, project_uid=policy.project_uid)
    if answer.decision == "refused" or answer.install:
        return SessionPlacement("refused", clip(answer.reason.replace("run this job", "start this session", 1)), code=answer.code or "requirement_unmet", candidates=list(answer.why),
                                detail=detail, project_uid=policy.project_uid)
    return SessionPlacement("here", clip(_here_reason(answer.reason, skipped)), candidates=list(answer.why), detail=detail,
                            project_uid=policy.project_uid)
