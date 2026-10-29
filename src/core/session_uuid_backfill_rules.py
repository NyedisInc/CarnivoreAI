
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from src.core.claude_project_dirs import (
    candidate_project_dirs,
    project_dir_names,
    same_directory,
)
from src.core.session_uuid_backfill import (
    ANCHOR_FAMILIES,
    CORROBORATING_SIGNALS,
    FILL_REQUIRES_SIGNALS,
    KIND_FILL,
    KIND_REPLACE,
    OUTCOME_AMBIGUOUS,
    OUTCOME_COLLIDES,
    OUTCOME_CONFIDENT,
    OUTCOME_NO_CANDIDATE,
    OUTCOME_SOUND,
    REPLACE_REQUIRES,
    SIGNAL_ACTIVE_IN_WINDOW,
    SIGNAL_PANE_ARGV,
    SIGNAL_PROJECT_DIR,
    SIGNAL_RECORDED_CWD,
    SIGNAL_SIBLING_ROW,
    SIGNAL_TITLE,
    UUID_ABSENT,
    UUID_PRESENT,
    Proposal,
    RowFacts,
    TranscriptFacts,
    classify_row,
    signal_families,
)

WINDOW_SLACK_SECONDS = 300


def _normalise_title(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _in_window(
    transcript: TranscriptFacts, row: RowFacts, *, now: float
) -> bool:
    if row.tmux_created_epoch is None:
        return False
    end = row.pane_window_end if row.pane_window_end is not None else now
    latest = transcript.last_ts if transcript.last_ts is not None else transcript.mtime
    if latest is None:
        return False
    return (
        row.tmux_created_epoch - WINDOW_SLACK_SECONDS
        <= latest
        <= end + WINDOW_SLACK_SECONDS
    )


def gather_signals(
    transcript: TranscriptFacts,
    row: RowFacts,
    *,
    argv_uuid: Optional[str],
    sibling_uuids: Set[str],
    project_dirs: Sequence[str],
    now: float,
) -> List[str]:
    found: Set[str] = set()
    if argv_uuid and transcript.uuid == argv_uuid:
        found.add(SIGNAL_PANE_ARGV)
    if transcript.uuid in sibling_uuids:
        found.add(SIGNAL_SIBLING_ROW)
    if transcript.recorded_cwd and same_directory(
        transcript.recorded_cwd, row.working_dir
    ):
        found.add(SIGNAL_RECORDED_CWD)
    if transcript.project_dir and transcript.project_dir in set(project_dirs):
        found.add(SIGNAL_PROJECT_DIR)
    if _in_window(transcript, row, now=now):
        found.add(SIGNAL_ACTIVE_IN_WINDOW)
    row_title = _normalise_title(row.title)
    if row_title and row_title == _normalise_title(transcript.name):
        found.add(SIGNAL_TITLE)
    return [s for s in CORROBORATING_SIGNALS if s in found]


def propose_for_row(
    row: RowFacts,
    transcripts: Sequence[TranscriptFacts],
    *,
    claims: Dict[str, int],
    argv_uuid: Optional[str] = None,
    sibling_uuids: Optional[Set[str]] = None,
    now: float,
    projects_dir: Optional[Path] = None,
    home: Optional[Path] = None,
    existing_dirs: Optional[Sequence[str]] = None,
) -> Proposal:
    on_disk = [t.uuid for t in transcripts]
    row_class = classify_row(row, on_disk)
    siblings = sibling_uuids or set()

    if row_class == UUID_PRESENT:
        return Proposal(
            row_id=row.row_id,
            row_class=row_class,
            outcome=OUTCOME_SOUND,
            detail="row already carries a uuid whose transcript exists",
        )

    dirs = project_dir_names(
        candidate_project_dirs(
            row.working_dir,
            projects_dir=projects_dir,
            home=home,
            existing=existing_dirs,
        )
    )

    scored: List[tuple] = []
    collided: List[tuple] = []
    for transcript in transcripts:
        if transcript.is_probe:
            continue
        signals = gather_signals(
            transcript,
            row,
            argv_uuid=argv_uuid,
            sibling_uuids=siblings,
            project_dirs=dirs,
            now=now,
        )
        if not signal_families(signals) & ANCHOR_FAMILIES:
            continue
        owner = claims.get(transcript.uuid)
        if owner is not None and owner != row.row_id:
            collided.append((transcript, signals, owner))
            continue
        scored.append((transcript, signals))

    decisive = [pair for pair in scored if SIGNAL_PANE_ARGV in pair[1]]
    if len(decisive) == 1:
        winners = decisive
    else:
        winners = [
            pair
            for pair in scored
            if len(signal_families(pair[1])) >= FILL_REQUIRES_SIGNALS
        ]

    argv_collision = [c for c in collided if SIGNAL_PANE_ARGV in c[1]]
    if argv_collision and not decisive:
        transcript, signals, owner = argv_collision[0]
        return Proposal(
            row_id=row.row_id,
            row_class=row_class,
            outcome=OUTCOME_COLLIDES,
            proposed_uuid=transcript.uuid,
            evidence=signals,
            collides_with=owner,
            candidates=[transcript.uuid],
            detail=(
                f"the pane's own argv names {transcript.uuid}, which row "
                f"{owner} already claims - a duplicate row pair for a human, "
                "never resolved here"
            ),
        )

    searched = (
        f"searched {len(dirs)} project "
        f"director{'y' if len(dirs) == 1 else 'ies'}"
    )

    if not winners:
        if not scored:
            return Proposal(
                row_id=row.row_id,
                row_class=row_class,
                outcome=OUTCOME_NO_CANDIDATE,
                detail=(
                    "no transcript on disk carries ANY evidence of being "
                    f"this row's conversation ({searched})"
                ),
            )
        return Proposal(
            row_id=row.row_id,
            row_class=row_class,
            outcome=OUTCOME_AMBIGUOUS,
            candidates=[t.uuid for t, _ in scored],
            evidence=sorted({s for _, sig in scored for s in sig}),
            detail=(
                f"{len(scored)} transcripts carry some evidence but none "
                "carries two INDEPENDENT kinds of it, so none can be told "
                f"apart from its neighbours ({searched})"
            ),
        )

    if len(winners) > 1:
        return Proposal(
            row_id=row.row_id,
            row_class=row_class,
            outcome=OUTCOME_AMBIGUOUS,
            candidates=[t.uuid for t, _ in winners],
            evidence=sorted({s for _, sig in winners for s in sig}),
            detail=(
                f"{len(winners)} transcripts each clear the evidence bar - "
                "refusing to break the tie"
            ),
        )

    transcript, signals = winners[0]
    kind = KIND_FILL if row_class == UUID_ABSENT else KIND_REPLACE

    if kind == KIND_REPLACE and not any(s in signals for s in REPLACE_REQUIRES):
        return Proposal(
            row_id=row.row_id,
            row_class=row_class,
            outcome=OUTCOME_AMBIGUOUS,
            candidates=[transcript.uuid],
            evidence=signals,
            detail=(
                "overwriting a recorded uuid needs the pane's own argv; a "
                "missing transcript is not proof the recorded value is wrong"
            ),
        )

    return Proposal(
        row_id=row.row_id,
        row_class=row_class,
        outcome=OUTCOME_CONFIDENT,
        kind=kind,
        proposed_uuid=transcript.uuid,
        evidence=signals,
        candidates=[transcript.uuid],
        detail=transcript.path,
    )


def sibling_uuid_map(rows: Sequence[RowFacts]) -> Dict[int, Set[str]]:
    out: Dict[int, Set[str]] = {r.row_id: set() for r in rows}
    for row in rows:
        for other in rows:
            if other.row_id == row.row_id or not other.recorded_uuid:
                continue
            same_tmux = bool(
                row.tmux_name and other.tmux_name and row.tmux_name == other.tmux_name
            )
            same_dir = same_directory(row.working_dir, other.working_dir)
            if same_tmux or same_dir:
                out[row.row_id].add(other.recorded_uuid)
    return out
