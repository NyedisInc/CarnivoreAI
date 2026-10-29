
from __future__ import annotations

from typing import Optional

STATUS_SOURCE_REGISTRY: str = "registry"

STATUS_SOURCE_PANE: str = "pane"

STATUS_SOURCE_TRANSCRIPT: str = "transcript"

STATUS_SOURCE_SEED_ROW: str = "seed_row"

STATUS_SOURCE_TMUX: str = "tmux"

STATUS_SOURCE_NONE: str = "none"

ALL_STATUS_SOURCES: frozenset[str] = frozenset(
    {
        STATUS_SOURCE_REGISTRY,
        STATUS_SOURCE_PANE,
        STATUS_SOURCE_TRANSCRIPT,
        STATUS_SOURCE_SEED_ROW,
        STATUS_SOURCE_TMUX,
        STATUS_SOURCE_NONE,
    }
)


def source_for_seed_rung(rung: Optional[str]) -> str:
    from src.core.session_status_seed import (
        SEED_RUNG_ROW,
        SEED_RUNG_TRANSCRIPT,
    )

    if rung == SEED_RUNG_ROW:
        return STATUS_SOURCE_SEED_ROW
    if rung == SEED_RUNG_TRANSCRIPT:
        return STATUS_SOURCE_TRANSCRIPT
    return STATUS_SOURCE_NONE
