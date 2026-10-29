
from __future__ import annotations

from typing import Optional, Tuple

from src.core.db_models import (
    SESSION_FORK_KIND_CLEAR,
    SESSION_FORK_KIND_COMPACT,
    SESSION_FORK_KIND_FORK,
)

SESSION_START_SOURCE_STARTUP = "startup"
SESSION_START_SOURCE_RESUME = "resume"

SESSION_START_SOURCE_REGISTRY = "registry"

PROCESS_BOOT_SOURCES: Tuple[str, ...] = (
    SESSION_START_SOURCE_STARTUP,
    SESSION_START_SOURCE_RESUME,
    SESSION_START_SOURCE_REGISTRY,
)

IN_PROCESS_TRANSITION_SOURCES: Tuple[str, ...] = (
    SESSION_FORK_KIND_FORK,
    SESSION_FORK_KIND_CLEAR,
    SESSION_FORK_KIND_COMPACT,
)

DIVERGENCE_SIBLING_PROCESS = "sibling_process"

DIVERGENCE_IN_PROCESS_FORK = "in_process_fork"

DIVERGENCE_SOURCE_UNRECOGNISED = "source_unrecognised"

DIVERGENCE_MINTS_A_ROW: Tuple[str, ...] = (
    DIVERGENCE_IN_PROCESS_FORK,
    DIVERGENCE_SOURCE_UNRECOGNISED,
)


def classify_uuid_divergence(source: Optional[str]) -> str:
    if isinstance(source, str):
        if source in PROCESS_BOOT_SOURCES:
            return DIVERGENCE_SIBLING_PROCESS
        if source in IN_PROCESS_TRANSITION_SOURCES:
            return DIVERGENCE_IN_PROCESS_FORK
    return DIVERGENCE_SOURCE_UNRECOGNISED


def mints_a_row(verdict: str) -> bool:
    return verdict in DIVERGENCE_MINTS_A_ROW
