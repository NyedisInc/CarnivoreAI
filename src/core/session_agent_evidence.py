
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
    """Pick the stronger of the two ``agent_type`` sources for a live session.

    Description: a four-rung ladder, strongest first. The order is the
      point; the values themselves are passed through untouched.

      1. An in-memory value this process did NOT fingerprint. The launcher
         chose it and ran it in this very process - nothing is closer to
         the truth.
      2. A non-blank datastore ``agent_type``. Usually a recorded launch
         decision, so it BEATS a fingerprint even though the fingerprint
         is more recent. When ``row_family_source`` says
         ``inferred_process`` the SAME rung answers with the SAME value,
         carried out as a guess (``from_process=True``, basis
         :data:`BASIS_RECORDED_ROW_INFERRED`) - a process read is a
         stronger guess than a scrollback scan, which is why it still
         outranks rung 3, and it is a guess, which is why it does not
         render like rung 2's usual answer.
      3. The in-memory value, which by elimination was fingerprinted.
         Carried through with ``from_fingerprint=True`` so it renders as
         the guess it is.
      4. Nothing. ``None`` with ``from_fingerprint=False``: not having
         looked is not the same as having looked and found no agent, and
         a "guessed nothing" would be a contradiction.
    Inputs:
      memory_agent_type (str | None) - ``Session.agent_type``.
      memory_from_fingerprint (bool) -
        ``Session.agent_type_via_fingerprint``.
      row_agent_type (str | None) - ``sessions.agent_type`` for this
        session's row, or None when there is no row / it could not be
        read. A blank string is treated as absent.
      row_family_source (str | None) - ``sessions.agent_family_source``
        on the SAME row. Optional: a caller that does not read it gets
        the pre-inference behaviour, in which every row value is a
        record. Never used to select a rung, only to label one.
    Output: AgentEvidence.
    Example:
      choose_agent_evidence(memory_agent_type="claude",
                            memory_from_fingerprint=True,
                            row_agent_type="claude-chrome").agent_type
        -> 'claude-chrome'
    """
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
