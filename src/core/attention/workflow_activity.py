
from __future__ import annotations

from typing import Optional

from src.core.attention.evidence import Evidence
from src.core.attention.process_scope import transcript_predates_process
from src.core.attention.transcript_facts import FACTS_FOUND, FACTS_NO_RECORD


def workflow_active(evidence: Optional[Evidence]) -> Optional[bool]:
    facts = getattr(evidence, "transcript", None)
    if facts is None:
        return None
    if facts.verdict not in (FACTS_FOUND, FACTS_NO_RECORD):
        return None
    if transcript_predates_process(evidence):
        return False
    trusted = (
        facts.pending_workflows if evidence.registry.trusts_pending_count else None
    )
    if facts.open_workflows > 0 or (trusted is not None and trusted > 0):
        return True
    if facts.verdict == FACTS_FOUND and trusted == 0:
        return False
    return None


__all__ = ["workflow_active"]
