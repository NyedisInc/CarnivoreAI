
from __future__ import annotations

from typing import List, Optional, Tuple

from src.core.agent_families import AGENT_FAMILY_BY_NAME, DEFAULT_FAMILY, AgentFamily

FAMILY_SOURCE_WRAPPER = "wrapper"
FAMILY_SOURCE_RESERVED_NAME = "reserved_name"
FAMILY_SOURCE_FINGERPRINT = "fingerprint"
# claude command
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
    """Resolve ``agent_type`` into a family for DISPLAY, honestly.

    DISPLAY-TIME RESOLVER - the counterpart to ``get_family`` /
    ``resolve_agent_type`` in ``src/core/agent_families.py``, and
    deliberately NOT merged with them. Those two exist to make sure a
    session always has something to run; this one exists to make sure a
    pill never claims a fact nobody measured. When the input cannot be
    resolved this returns ``(None, "unknown")`` - never
    ``AGENT_FAMILY_BY_NAME[DEFAULT_FAMILY]``. A caller that wants a value
    to launch with must call ``get_family`` / ``resolve_agent_type``
    instead; this function is not a drop-in replacement for either.

    Inputs:
      agent_type (str | None) - the stored/requested value, same shape as
        ``resolve_agent_type`` accepts (a wrapper id OR a bare family
        name); case-insensitive.
      wrappers (list) - every configured wrapper, ``AgentWrapper`` objects
        or AgentWrapper-shaped dicts (same dual-type contract as
        ``wrappers_for_family``).
      from_fingerprint (bool) - True iff the caller already knows this
        ``agent_type`` value was produced by scrollback fingerprinting
        rather than an explicit launch/config choice. The resolver has no
        way to infer this on its own - a fingerprinted value that landed
        on "codex" is textually identical to an explicit "codex" launch -
        so the caller must say so. Defaults to False (the common case:
        launched or config-derived).
      from_process (bool) - True iff this ``agent_type`` was inferred
        from the pane's process tree. THE TWO GUESS FLAGS ARE MUTUALLY
        EXCLUSIVE by construction: one evidence ladder answers per
        session and it sets exactly one basis. If a caller ever asserts
        both, ``from_fingerprint`` wins - the WEAKER label - so a
        contradiction under-claims rather than over-claims. It never
        raises, because this decorates a listing and a listing must not
        fail over a provenance label.
    Output:
      (AgentFamily | None, str) - the resolved family (or None when it
      could not be determined) and one of ``DISPLAY_FAMILY_SOURCES``.
    Example:
      resolve_family_for_display("deleted-wrapper-id", []) -> (None, "unknown")
      resolve_family_for_display("codex", []) -> (codex family, "reserved_name")
    """
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
