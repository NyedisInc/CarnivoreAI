
from __future__ import annotations

from typing import FrozenSet, Mapping, Optional, Tuple

WRAPPER_FROM_ROW_CORROBORATED: str = "row_corroborated_by_process"
WRAPPER_FROM_PROCESS: str = "process_unique_match"
WRAPPER_FROM_ROW: str = "row_only"
WRAPPER_FROM_TIE_DEFAULT: str = "process_tie_broken_by_default"
WRAPPER_INFERRED_DEFAULT: str = "inferred_default_no_evidence"
WRAPPER_NONE: str = "none"

CONVERSATION_MEASURED: str = "measured"
CONVERSATION_RECORDED: str = "recorded"


def pick_conversation(
    measured: Optional[str], recorded: Optional[str]
) -> Tuple[Optional[str], Optional[str], bool]:
    if measured:
        return measured, CONVERSATION_MEASURED, measured == recorded
    if recorded:
        return recorded, CONVERSATION_RECORDED, False
    return None, None, False


def choose_wrapper(
    row_agent_type: Optional[str],
    observed: Optional[FrozenSet[str]],
    signatures: Mapping[str, FrozenSet[str]],
    default_id: Optional[str],
) -> Tuple[Optional[str], str, str]:
    row = row_agent_type if row_agent_type in signatures else None
    if observed is None:
        if row:
            return row, WRAPPER_FROM_ROW, "the recorded wrapper; no live process was seen"
        if default_id in signatures:
            return default_id, WRAPPER_INFERRED_DEFAULT, (
                "no recorded wrapper and no live process: the default wrapper, "
                "which is a guess"
            )
        return None, WRAPPER_NONE, "no wrapper recorded, seen, or configured as default"
    if row and signatures[row] == observed:
        return row, WRAPPER_FROM_ROW_CORROBORATED, "the recorded wrapper, matching the live process"
    matches = [i for i, sig in signatures.items() if sig == observed]
    if len(matches) == 1:
        note = f"; the record said {row_agent_type}" if row_agent_type and row_agent_type != matches[0] else ""
        return matches[0], WRAPPER_FROM_PROCESS, f"the only wrapper matching the live process{note}"
    if matches:
        if row in matches:
            return row, WRAPPER_FROM_ROW_CORROBORATED, (
                f"the recorded wrapper; the live process also fits {', '.join(matches)}"
            )
        pick = default_id if default_id in matches else matches[0]
        return pick, WRAPPER_FROM_TIE_DEFAULT, (
            f"the live process fits {', '.join(matches)}; {pick} was picked"
        )
    return None, WRAPPER_NONE, (
        f"no configured wrapper carries exactly {' '.join(sorted(observed))}"
    )


def missing_flags(
    observed: Optional[FrozenSet[str]], resolved: Optional[FrozenSet[str]]
) -> FrozenSet[str]:
    """Observed wrapper flags the resolved launch would NOT carry.

    Description: ``resolved`` None means the wrapper's script could not be
      read; every observed flag then counts as missing, because an unread
      file cannot be claimed to carry anything.
    Inputs: observed (frozenset | None). resolved (frozenset | None).
    Output: frozenset - empty when nothing is lost or nothing was observed.
    Example: missing_flags(frozenset({'--chrome'}), frozenset())  # {'--chrome'}
    """
    if not observed:
        return frozenset()
    return frozenset(observed - (resolved or frozenset()))

