
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple


UUID_ABSENT = "uuid_absent"

UUID_PRESENT = "uuid_present"

UUID_PHANTOM = "uuid_phantom"


OUTCOME_CONFIDENT = "confident"

OUTCOME_AMBIGUOUS = "ambiguous"

OUTCOME_NO_CANDIDATE = "no_candidate"

OUTCOME_SOUND = "sound"

OUTCOME_COLLIDES = "collides_with_existing_row"

OUTCOME_NOT_WRITABLE: Tuple[str, ...] = (
    OUTCOME_AMBIGUOUS,
    OUTCOME_NO_CANDIDATE,
    OUTCOME_SOUND,
    OUTCOME_COLLIDES,
)


KIND_FILL = "fill"

KIND_REPLACE = "replace"


SIGNAL_PANE_ARGV = "pane_argv"

SIGNAL_PROJECT_DIR = "project_dir"

SIGNAL_RECORDED_CWD = "recorded_cwd"

SIGNAL_ACTIVE_IN_WINDOW = "active_in_window"

SIGNAL_SIBLING_ROW = "sibling_row"

SIGNAL_TITLE = "title_match"

CORROBORATING_SIGNALS: Tuple[str, ...] = (
    SIGNAL_PANE_ARGV,
    SIGNAL_SIBLING_ROW,
    SIGNAL_RECORDED_CWD,
    SIGNAL_PROJECT_DIR,
    SIGNAL_ACTIVE_IN_WINDOW,
    SIGNAL_TITLE,
)

SIGNAL_FAMILIES = {
    SIGNAL_PANE_ARGV: "identity",
    SIGNAL_SIBLING_ROW: "lineage",
    SIGNAL_RECORDED_CWD: "location",
    SIGNAL_PROJECT_DIR: "location",
    SIGNAL_ACTIVE_IN_WINDOW: "timing",
    SIGNAL_TITLE: "naming",
}

ANCHOR_FAMILIES = frozenset({"identity", "lineage", "location"})

FILL_REQUIRES_SIGNALS = 2


def signal_families(signals: Sequence[str]) -> Set[str]:
    return {SIGNAL_FAMILIES.get(s, s) for s in signals}

REPLACE_REQUIRES: Tuple[str, ...] = (SIGNAL_PANE_ARGV,)


@dataclass(frozen=True)
class RowFacts:

    row_id: int
    working_dir: Optional[str] = None
    tmux_name: Optional[str] = None
    tmux_created_epoch: Optional[int] = None
    recorded_uuid: Optional[str] = None
    lifecycle: str = "unknown"
    archived: bool = False
    title: Optional[str] = None
    pane_window_end: Optional[float] = None


@dataclass(frozen=True)
class TranscriptFacts:

    uuid: str
    path: str
    project_dir: str = ""
    recorded_cwd: Optional[str] = None
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None
    mtime: Optional[float] = None
    is_probe: bool = False
    name: Optional[str] = None


@dataclass(frozen=True)
class Proposal:

    row_id: int
    row_class: str
    outcome: str
    kind: Optional[str] = None
    proposed_uuid: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    detail: Optional[str] = None
    collides_with: Optional[int] = None
    candidates: List[str] = field(default_factory=list)

    @property
    def writable(self) -> bool:
        return (
            self.outcome == OUTCOME_CONFIDENT
            and bool(self.proposed_uuid)
            and self.kind is not None
        )


def classify_row(row: RowFacts, transcript_uuids: Sequence[str]) -> str:
    if not row.recorded_uuid:
        return UUID_ABSENT
    return UUID_PRESENT if row.recorded_uuid in set(transcript_uuids) else UUID_PHANTOM


def parse_epoch(value: Optional[str]) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
