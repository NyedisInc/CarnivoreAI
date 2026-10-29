
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.db_models import SESSION_FAMILY_SOURCE_INFERRED_PROCESS

BASIS_MEMORY_LAUNCH = "memory_launch"
BASIS_RECORDED_ROW = "recorded_row"
BASIS_RECORDED_ROW_INFERRED = "recorded_row_inferred"
BASIS_MEMORY_FINGERPRINT = "memory_fingerprint"
BASIS_NONE = "none"


@dataclass(frozen=True)
class AgentEvidence:

    agent_type: Optional[str]
    from_fingerprint: bool
    basis: str
    from_process: bool = False


def choose_agent_evidence(
    *,
    memory_agent_type: Optional[str],
    memory_from_fingerprint: bool,
    row_agent_type: Optional[str],
    row_family_source: Optional[str] = None,
) -> AgentEvidence:
    memory = (memory_agent_type or "").strip()
    row = (row_agent_type or "").strip()

    if memory and not memory_from_fingerprint:
        return AgentEvidence(memory_agent_type, False, BASIS_MEMORY_LAUNCH)

    if row:
        if (row_family_source or "").strip() == SESSION_FAMILY_SOURCE_INFERRED_PROCESS:
            return AgentEvidence(
                row_agent_type,
                False,
                BASIS_RECORDED_ROW_INFERRED,
                from_process=True,
            )
        return AgentEvidence(row_agent_type, False, BASIS_RECORDED_ROW)

    if memory:
        return AgentEvidence(memory_agent_type, True, BASIS_MEMORY_FINGERPRINT)

    return AgentEvidence(None, False, BASIS_NONE)


def recorded_launch_family(
    *,
    row_agent_family: Optional[str],
    row_family_source: Optional[str],
    row_agent_type: Optional[str],
    effective_agent_type: Optional[str],
) -> Optional[tuple]:
    from src.core.agent_families import AGENT_FAMILY_BY_NAME
    from src.core.session_agent_provenance import DEFINITE_LAUNCH_SOURCES

    stored = (row_agent_family or "").strip().lower()
    if not stored:
        return None
    if (row_family_source or "").strip() not in DEFINITE_LAUNCH_SOURCES:
        return None
    if (row_agent_type or "").strip().lower() != (
        effective_agent_type or ""
    ).strip().lower():
        return None
    family = AGENT_FAMILY_BY_NAME.get(stored)
    if family is None:
        return None
    return family, (row_family_source or "").strip()
