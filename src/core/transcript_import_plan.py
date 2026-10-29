
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.message_model_serialize import (
    AGENT_SCHEME,
    UUID_SCHEME,
    session_ref_scheme,
)
from src.core.db_models import (
    PROJECT_SOURCE_TRANSCRIPT_IMPORT,
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_LIFECYCLE_SOURCE_IMPORT,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_IMPORTED,
)
from src.core.transcript_import_facts import TranscriptFacts
from src.core.transcript_import_paths import (
    canonical,
    git_top_level,
    is_scratch,
    match_project,
    truncate_title,
)

PLAN_IMPORT = "import"

PLAN_ALREADY_PRESENT = "already_present"

PLAN_EXCLUDED_SCRATCH = "excluded_scratch"

PLAN_NOT_A_CONVERSATION = "not_a_conversation"

PLAN_NOT_A_SESSION_REF = "not_a_session_ref"

PLAN_DUPLICATE_TRANSCRIPT = "duplicate_transcript"

@dataclass(frozen=True)
class ProposedSession:

    outcome: str
    claude_session_uuid: str
    working_dir: Optional[str] = None
    recorded_cwd: Optional[str] = None
    project_root: Optional[str] = None
    project_exists: bool = False
    project_rule: Optional[str] = None
    title: Optional[str] = None
    title_source: Optional[str] = None
    created_at: Optional[str] = None
    last_work_at: Optional[str] = None
    transcript_path: Optional[str] = None
    detail: Optional[str] = None

    @property
    def writes(self) -> bool:
        return self.outcome == PLAN_IMPORT


def _title_for(facts: TranscriptFacts) -> Tuple[Optional[str], Optional[str]]:
    if facts.custom_title:
        return truncate_title(facts.custom_title), "custom-title"
    text = truncate_title(facts.first_user_text)
    return (text, "first_user_message") if text else (None, None)


def plan_transcript(
    facts: TranscriptFacts,
    *,
    held_uuids: Sequence[str],
    project_roots: Sequence[str],
    home: Optional[str] = None,
) -> ProposedSession:
    uuid = facts.uuid
    if not facts.is_conversation:
        return ProposedSession(
            outcome=PLAN_NOT_A_CONVERSATION,
            claude_session_uuid=uuid,
            detail=facts.detail,
        )
    scheme = session_ref_scheme(uuid)
    if scheme != UUID_SCHEME:
        return ProposedSession(
            outcome=PLAN_NOT_A_SESSION_REF,
            claude_session_uuid=uuid,
            recorded_cwd=facts.cwd,
            detail=(
                f"the transcript is named {uuid!r}, a {scheme!r}-scheme ref: "
                + (
                    "a subagent's run inside another conversation, not a "
                    "conversation of its own"
                    if scheme == AGENT_SCHEME
                    else "a string naming no identity scheme this corpus "
                    "recognises, so no restart could address it"
                )
            ),
        )
    if uuid in set(held_uuids):
        return ProposedSession(
            outcome=PLAN_ALREADY_PRESENT,
            claude_session_uuid=uuid,
            recorded_cwd=facts.cwd,
            detail=(
                "a sessions row already holds this conversation, so the "
                "import leaves it alone rather than writing over columns "
                "a live session may own"
            ),
        )
    if is_scratch(facts.cwd):
        return ProposedSession(
            outcome=PLAN_EXCLUDED_SCRATCH,
            claude_session_uuid=uuid,
            recorded_cwd=facts.cwd,
            detail=(
                f"the conversation ran in {facts.cwd!r}, a per-run scratch "
                "directory that can never be a project root"
            ),
        )

    working_dir = canonical(facts.cwd) or facts.cwd
    matched = match_project(working_dir, project_roots)
    if matched is not None:
        project_root, rule, exists = matched, "matched", True
    else:
        top = git_top_level(working_dir, home=home)
        project_root = top or working_dir
        rule = "git_toplevel" if top else "cwd"
        exists = False

    title, title_source = _title_for(facts)
    return ProposedSession(
        outcome=PLAN_IMPORT,
        claude_session_uuid=uuid,
        working_dir=working_dir,
        recorded_cwd=facts.cwd,
        project_root=project_root,
        project_exists=exists,
        project_rule=rule,
        title=title,
        title_source=title_source,
        created_at=facts.first_ts,
        last_work_at=facts.last_ts or facts.first_ts,
        transcript_path=facts.path,
    )


IMPORTED_ROW_CONSTANTS: Dict[str, object] = {
    "origin": SESSION_ORIGIN_IMPORTED,
    "lifecycle": SESSION_LIFECYCLE_STOPPED,
    "lifecycle_source": SESSION_LIFECYCLE_SOURCE_IMPORT,
    "project_attribution": SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    "claude_session_uuid_source": SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
}

IMPORTED_PROJECT_SOURCE: str = PROJECT_SOURCE_TRANSCRIPT_IMPORT


def summarise(plans: Sequence[ProposedSession]) -> Dict[str, int]:
    counts = {
        PLAN_IMPORT: 0,
        PLAN_ALREADY_PRESENT: 0,
        PLAN_EXCLUDED_SCRATCH: 0,
        PLAN_NOT_A_CONVERSATION: 0,
        PLAN_NOT_A_SESSION_REF: 0,
        PLAN_DUPLICATE_TRANSCRIPT: 0,
    }
    for plan in plans:
        counts[plan.outcome] = counts.get(plan.outcome, 0) + 1
    return counts


def projects_to_create(plans: Sequence[ProposedSession]) -> List[str]:
    return sorted(
        {
            plan.project_root
            for plan in plans
            if plan.writes and not plan.project_exists and plan.project_root
        }
    )


def dedupe_by_uuid(plans: Sequence[ProposedSession]) -> List[ProposedSession]:
    winner: Dict[str, int] = {}
    for index, plan in enumerate(plans):
        if not plan.writes:
            continue
        held = winner.get(plan.claude_session_uuid)
        if held is None:
            winner[plan.claude_session_uuid] = index
            continue
        incumbent = plans[held]
        if (plan.last_work_at or "") > (incumbent.last_work_at or ""):
            winner[plan.claude_session_uuid] = index

    keep = set(winner.values())
    out: List[ProposedSession] = []
    for index, plan in enumerate(plans):
        if not plan.writes or index in keep:
            out.append(plan)
            continue
        kept = plans[winner[plan.claude_session_uuid]]
        out.append(
            ProposedSession(
                outcome=PLAN_DUPLICATE_TRANSCRIPT,
                claude_session_uuid=plan.claude_session_uuid,
                recorded_cwd=plan.recorded_cwd,
                detail=(
                    "another transcript in this pass carries the same "
                    f"conversation with later activity ({kept.recorded_cwd!r}), "
                    "so this one is the older spelling of the same session"
                ),
            )
        )
    return out
