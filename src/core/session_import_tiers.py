
from __future__ import annotations

from typing import Optional

from src.core.product_identity import strip_session_prefix
from src.core.session_import_ladder_types import (
    ORIGIN_MARKER_CREATED,
    TIER_HIT,
    TIER_MISS,
    TIER_UNEVALUATED,
    LadderEvidence,
    LiveSession,
    TierOutcome,
)


def _tier1_owned_set(
    session: LiveSession, evidence: LadderEvidence
) -> TierOutcome:
    if evidence.owned_tmux_names is None:
        return TierOutcome(
            tier=1,
            name="owned_set",
            result=TIER_UNEVALUATED,
            detail="the owned-set file could not be read",
        )
    try:
        hit = session.tmux_name in evidence.owned_tmux_names
    except (OSError, ValueError, TypeError) as exc:
        return TierOutcome(
            tier=1,
            name="owned_set",
            result=TIER_UNEVALUATED,
            detail=f"the owned set could not be searched: {exc}",
        )
    return TierOutcome(
        tier=1,
        name="owned_set",
        result=TIER_HIT if hit else TIER_MISS,
        detail="named in the persisted owned set" if hit else "not in the owned set",
    )


def created_pipe_slug_for(tmux_name: str) -> Optional[str]:
    return strip_session_prefix(tmux_name) or None


def _tier3_created_pipe(
    session: LiveSession, evidence: LadderEvidence
) -> TierOutcome:
    if evidence.created_pipe_slugs is None:
        return TierOutcome(
            tier=3,
            name="created_pipe",
            result=TIER_UNEVALUATED,
            detail="the log directory could not be read",
        )
    slug = created_pipe_slug_for(session.tmux_name)
    if slug is None:
        return TierOutcome(
            tier=3,
            name="created_pipe",
            result=TIER_MISS,
            detail="the name carries no recoverable slug (user-typed name)",
        )
    try:
        hit = slug in evidence.created_pipe_slugs
    except (OSError, ValueError, TypeError) as exc:
        return TierOutcome(
            tier=3,
            name="created_pipe",
            result=TIER_UNEVALUATED,
            detail=f"the pipe set could not be searched: {exc}",
        )
    return TierOutcome(
        tier=3,
        name="created_pipe",
        result=TIER_HIT if hit else TIER_MISS,
        detail=(
            f"tmux_{slug}.pipe exists, which only the create path writes"
            if hit
            else f"no tmux_{slug}.pipe"
        ),
    )


def _tier4_origin_marker(
    session: LiveSession, evidence: LadderEvidence
) -> TierOutcome:
    name = "origin_marker"
    if session.tmux_name in evidence.origin_probe_failures:
        return TierOutcome(
            tier=4,
            name=name,
            result=TIER_UNEVALUATED,
            detail="the tmux environment could not be read for this session",
        )
    marker = evidence.origin_markers.get(session.tmux_name)
    if marker != ORIGIN_MARKER_CREATED:
        return TierOutcome(
            tier=4,
            name=name,
            result=TIER_MISS,
            detail=(
                "no CLOUDECODE_ORIGIN=created in the session environment"
                if marker is None
                else f"CLOUDECODE_ORIGIN is {marker!r}, not 'created'"
            ),
        )
    if evidence.stage_a_boundary_epoch is None:
        return TierOutcome(
            tier=4,
            name=name,
            result=TIER_UNEVALUATED,
            detail=(
                "a CLOUDECODE_ORIGIN marker is present but this install's "
                "Stage-A boundary is unknown, so the marker cannot be dated "
                "and is INADMISSIBLE rather than assumed valid"
            ),
        )
    if session.epoch is None:
        return TierOutcome(
            tier=4,
            name=name,
            result=TIER_UNEVALUATED,
            detail=(
                "a marker is present but the session has no creation epoch, "
                "so it cannot be placed relative to the Stage-A boundary"
            ),
        )
    if int(session.epoch) < int(evidence.stage_a_boundary_epoch):
        return TierOutcome(
            tier=4,
            name=name,
            result=TIER_MISS,
            detail=(
                f"a marker is present but the session epoch {session.epoch} "
                f"predates this install's Stage-A boundary "
                f"{evidence.stage_a_boundary_epoch}, so it is IGNORED"
            ),
        )
    return TierOutcome(
        tier=4,
        name=name,
        result=TIER_HIT,
        detail="CLOUDECODE_ORIGIN=created, stamped after this install's Stage-A boundary",
    )
