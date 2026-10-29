
from __future__ import annotations

from typing import List, Sequence, Tuple

import structlog

from src.core.session_import_ladder_types import (
    AUTO_NAME_RE,
    INADMISSIBLE_TIERS,
    LADDER_OURS,
    LADDER_THEIRS,
    LADDER_UNKNOWN,
    ORIGIN_MARKER_CREATED,
    REASON_COULD_NOT_EVALUATE,
    REASON_NO_EVIDENCE,
    SESSION_PREFIX,
    TIER_HIT,
    TIER_MISS,
    TIER_UNEVALUATED,
    LadderEvidence,
    LadderReport,
    LiveSession,
    SessionVerdict,
    TierOutcome,
)
from src.core.session_import_tiers import (
    _tier1_owned_set,
    _tier3_created_pipe,
    _tier4_origin_marker,
    created_pipe_slug_for,
)

__all__ = [
    "AUTO_NAME_RE",
    "INADMISSIBLE_TIERS",
    "LADDER_OURS",
    "LADDER_THEIRS",
    "LADDER_UNKNOWN",
    "ORIGIN_MARKER_CREATED",
    "REASON_COULD_NOT_EVALUATE",
    "REASON_NO_EVIDENCE",
    "SESSION_PREFIX",
    "TIER_HIT",
    "TIER_MISS",
    "TIER_UNEVALUATED",
    "LadderEvidence",
    "LadderReport",
    "LiveSession",
    "SessionVerdict",
    "TierOutcome",
    "classify",
    "collect_hints",
    "created_pipe_slug_for",
    "decide",
]

logger = structlog.get_logger()


_ADMISSIBLE_TIERS = (_tier1_owned_set, _tier3_created_pipe, _tier4_origin_marker)


def collect_hints(
    session: LiveSession, evidence: LadderEvidence
) -> Tuple[str, ...]:
    hints: List[str] = []
    if AUTO_NAME_RE.match(session.tmux_name):
        hints.append(
            "its name matches the auto-generated form Carnivore uses "
            "when you do not type one"
        )
    wd = session.working_dir
    if wd:
        for root in evidence.project_roots:
            if wd == root or wd.startswith(root.rstrip("/") + "/"):
                hints.append(f"it is running in your project folder {root}")
                break
    return tuple(hints)


def decide(session: LiveSession, evidence: LadderEvidence) -> SessionVerdict:
    outcomes: List[TierOutcome] = [fn(session, evidence) for fn in _ADMISSIBLE_TIERS]
    hints = collect_hints(session, evidence)
    try:
        readopted = session.tmux_name in evidence.ext_pipe_names
    except (OSError, ValueError, TypeError):
        readopted = False

    hit = next((o for o in outcomes if o.result == TIER_HIT), None)
    unevaluated = tuple(o.name for o in outcomes if o.result == TIER_UNEVALUATED)

    if hit is not None:
        readopted = readopted and hit.name == "created_pipe"
        return SessionVerdict(
            tmux_name=session.tmux_name,
            epoch=session.epoch,
            verdict=LADDER_OURS,
            reason=hit.name,
            tiers=tuple(outcomes),
            hints=hints,
            unevaluated=unevaluated,
            readopted=readopted,
        )

    return SessionVerdict(
        tmux_name=session.tmux_name,
        epoch=session.epoch,
        verdict=LADDER_UNKNOWN,
        reason=(
            REASON_COULD_NOT_EVALUATE if unevaluated else REASON_NO_EVIDENCE
        ),
        tiers=tuple(outcomes),
        hints=hints,
        unevaluated=unevaluated,
        readopted=False,
    )


def classify(
    sessions: Sequence[LiveSession], evidence: LadderEvidence
) -> LadderReport:
    verdicts = tuple(decide(s, evidence) for s in sessions)
    report = LadderReport(verdicts=verdicts)
    logger.info(
        "session_import_ladder_classified",
        total=len(verdicts),
        ours=len(report.ours),
        theirs=len(report.theirs),
        unknown_no_evidence=len(report.unknown_no_evidence),
        unknown_could_not_evaluate=len(report.unknown_unevaluated),
    )
    return report
