"""Which wrapper a WAKE may launch without asking. PURE.

THE DEAD END THIS CLOSES (issue #714). ``POST /sessions/{uuid}/wake`` used
to hand the row's ``agent_type`` straight to the recreate action, whose
wrapper gate (``session_agent_choice.validate_agent_choice``) accepts only
configured wrapper ids. A row carrying anything else - the bare family
``claude`` the create path used to record (issue #713), a wrapper deleted
since, or an inferred value - came back ``cannot_determine`` and the user
saw "could not wake" with nothing to do about it.

TWO RULES, neither of them a guess.

  AN INFERENCE IS NOT INTENT. A value process inference wrote describes
  what a pane was running, not what to start; ``restart_agent_type`` is
  the sanctioned filter and it is used here, so a wake never launches an
  inference.

  A RECORDED VALUE IS USED ONLY WHEN IT IS A CONFIGURED WRAPPER. Anything
  else is not mapped to some wrapper on the user's behalf; the wake answers
  ``wrapper_needed`` with the ids that do exist, the client opens the
  existing wrapper picker, and the pick comes back to the same wake route.
  The recreate then records it on the row (``launch_record``), so the user
  picks once.

When the wrapper list could not be READ, the recorded value is passed
through untouched: whether it is valid is unknown, and the recreate gate
already answers that honestly (``cannot_determine``) rather than this
module calling it invalid.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from src.core.session_agent_infer import restart_agent_type

WAKE_WRAPPER_NEEDED: str = "wrapper_needed"


def recorded_wake_agent(
    row: Mapping[str, Any], configured_ids: Optional[Iterable[str]]
) -> Optional[str]:
    """The row's own wrapper, when a wake may launch it without asking.

    Inputs: row (Mapping) - the ``sessions`` row being woken.
      configured_ids (Iterable[str] | None) - the configured wrapper ids,
      or None when the list could not be read.
    Output: str | None - the wrapper id to wake under, or None when the
      user has to pick one.
    Example: recorded_wake_agent({'agent_type': 'claude',
      'agent_family_source': 'launched'}, ['keyc'])  # None
    """
    usable = restart_agent_type(row.get("agent_type"), row.get("agent_family_source"))
    value = (usable or "").strip()
    if not value:
        return None
    if configured_ids is None:
        return value
    return value if value in set(configured_ids) else None


def wrapper_needed_detail(row: Mapping[str, Any], configured_ids: Iterable[str]) -> str:
    ids = list(configured_ids)
    recorded = (row.get("agent_type") or "").strip()
    inferred = recorded and restart_agent_type(recorded, row.get("agent_family_source")) is None
    if not recorded:
        why = "this session has no recorded wrapper"
    elif inferred:
        why = f"'{recorded}' was inferred from the pane, not chosen, so it is not launched unasked"
    else:
        why = f"'{recorded}' is not a configured launch wrapper"
    have = ", ".join(ids) if ids else "none"
    return f"{why}. pick a wrapper to wake it with; this install has {have}"
