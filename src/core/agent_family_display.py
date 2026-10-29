
from __future__ import annotations

from typing import List, Optional, Tuple

from src.core.agent_families import AGENT_FAMILY_BY_NAME, DEFAULT_FAMILY, AgentFamily

FAMILY_SOURCE_WRAPPER = "wrapper"
FAMILY_SOURCE_RESERVED_NAME = "reserved_name"
FAMILY_SOURCE_FINGERPRINT = "fingerprint"
FAMILY_SOURCE_INFERRED_PROCESS = "inferred_process"
FAMILY_SOURCE_DERIVED_DEEPEST = "derived_deepest"
FAMILY_SOURCE_UNKNOWN = "unknown"

DISPLAY_FAMILY_SOURCES: Tuple[str, ...] = (
    FAMILY_SOURCE_WRAPPER,
    FAMILY_SOURCE_RESERVED_NAME,
    FAMILY_SOURCE_FINGERPRINT,
    FAMILY_SOURCE_INFERRED_PROCESS,
    FAMILY_SOURCE_DERIVED_DEEPEST,
    FAMILY_SOURCE_UNKNOWN,
)


def _guess_source(from_fingerprint: bool, from_process: bool) -> Optional[str]:
    if from_fingerprint:
        return FAMILY_SOURCE_FINGERPRINT
    if from_process:
        return FAMILY_SOURCE_INFERRED_PROCESS
    return None


def resolve_family_for_display(
    agent_type: Optional[str],
    wrappers: List,
    *,
    from_fingerprint: bool = False,
    from_process: bool = False,
) -> Tuple[Optional[AgentFamily], str]:
    normalized = (agent_type or "").strip().lower()
    if not normalized:
        return None, FAMILY_SOURCE_UNKNOWN

    guess_source = _guess_source(from_fingerprint, from_process)

    if normalized in AGENT_FAMILY_BY_NAME:
        family = AGENT_FAMILY_BY_NAME[normalized]
        if guess_source:
            return family, guess_source
        return family, FAMILY_SOURCE_RESERVED_NAME

    for w in wrappers:
        if isinstance(w, dict):
            wid = w.get("id")
            has_family_key = "family" in w
            family_name = w.get("family") or None
        else:
            wid = getattr(w, "id", None)
            has_family_key = hasattr(w, "family")
            family_name = getattr(w, "family", None) or None
        if wid != normalized:
            continue

        if family_name is not None and family_name in AGENT_FAMILY_BY_NAME:
            family = AGENT_FAMILY_BY_NAME[family_name]
            if guess_source:
                return family, guess_source
            return family, FAMILY_SOURCE_WRAPPER

        if not has_family_key or not family_name:
            family = AGENT_FAMILY_BY_NAME[DEFAULT_FAMILY]
            if guess_source:
                return family, guess_source
            return family, FAMILY_SOURCE_DERIVED_DEEPEST

        return None, FAMILY_SOURCE_UNKNOWN

    return None, FAMILY_SOURCE_UNKNOWN
