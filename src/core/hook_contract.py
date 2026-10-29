"""The contract between Claude Code's hook system and this app.

WHAT THIS IS FOR. Three things this app could not previously do:

  1. **Classify** an inbound hook - is this event one we know, one Claude
     ships but we ignore, or one that did not exist when this code was
     written? Those are three different facts and the endpoint used to
     collapse the last two into "not subscribed, drop it".
  2. **Act** on the classification with a stated reason, rather than a
     silent drop.
  3. **Check future shapes.** Claude Code ships new hook events and new
     payload fields on its own schedule. Without a recorded contract, a
     new event is indistinguishable from an event we forgot, and a
     REMOVED event is invisible entirely - the subscription simply stops
     firing and every state it fed becomes permanently unreachable while
     looking fully implemented.

WHAT IS DELIBERATELY NOT HERE. No payload VALIDATION that rejects. A hook
whose payload gained a field must not be dropped - the extra field is
Claude telling us something new, and refusing it would turn a feature
addition into an outage. ``classify_payload`` reports what it saw; the
caller decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

MEASURED_AGAINST_VERSION: str = "2.1.248"
MEASURED_ON: str = "not measured"

ALL_HOOK_EVENTS: Tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Notification",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "SessionStart",
    "SessionEnd",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "PermissionRequest",
    "PermissionDenied",
    "Setup",
    "TeammateIdle",
    "TaskCreated",
    "TaskCompleted",
    "Elicitation",
    "ElicitationResult",
    "ConfigChange",
    "WorktreeCreate",
    "WorktreeRemove",
    "InstructionsLoaded",
    "CwdChanged",
    "FileChanged",
    "DirectoryAdded",
    "MessageDisplay",
)

SESSION_START_SOURCES: Tuple[str, ...] = (
    "startup",
    "resume",
    "clear",
    "compact",
    "fork",
)

SESSION_END_REASONS: Tuple[str, ...] = (
    "clear",
    "resume",
    "logout",
    "prompt_input_exit",
    "other",
)


@dataclass(frozen=True)
class HookEvent:

    name: str
    subscribed: bool
    role: str
    why: str


ROLE_TOAST = "toast"
ROLE_ACTIVITY = "activity"
ROLE_LIFECYCLE = "lifecycle"
ROLE_NONE = "none"

_UNREVIEWED = (
    "not reviewed - shipped by Claude, no decision recorded here yet"
)

HOOK_REGISTRY: Tuple[HookEvent, ...] = (
    HookEvent("Stop", True, ROLE_TOAST, "turn finished - drives unread + toast"),
    HookEvent("Notification", True, ROLE_TOAST, "claude is asking - drives the question state"),
    HookEvent("PermissionRequest", True, ROLE_TOAST, "blocked on a permission decision - question state"),
    HookEvent("UserPromptSubmit", True, ROLE_ACTIVITY, "a turn started - clears unread, begins working"),
    HookEvent("PreToolUse", True, ROLE_ACTIVITY, "working heartbeat"),
    HookEvent("PostToolUse", True, ROLE_ACTIVITY, "working heartbeat"),
    HookEvent("SubagentStart", True, ROLE_ACTIVITY, "drives working_subagent"),
    HookEvent("SubagentStop", True, ROLE_ACTIVITY, "ends working_subagent"),
    HookEvent("SessionStart", True, ROLE_LIFECYCLE, "binds claude_session_uuid, lineage, claude_title"),
    HookEvent("SessionEnd", True, ROLE_LIFECYCLE, "marks the conversation ended"),
    HookEvent(
        "StopFailure", False, ROLE_NONE,
        "KNOWN GAP: a turn killed by a rate limit fires this and NOT Stop, "
        "so the unread flag is never written and the session decays to idle "
        "on heartbeat expiry - it reads as finished work when it is failed "
        "work. Subscribing is the fix; nothing here depends on it staying off",
    ),
    HookEvent("PostToolUseFailure", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("PostToolBatch", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("UserPromptExpansion", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("PreCompact", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("PostCompact", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("PermissionDenied", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("Setup", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("TeammateIdle", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("TaskCreated", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("TaskCompleted", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("Elicitation", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("ElicitationResult", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("ConfigChange", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("WorktreeCreate", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("WorktreeRemove", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("InstructionsLoaded", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("CwdChanged", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("FileChanged", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("DirectoryAdded", False, ROLE_NONE, _UNREVIEWED),
    HookEvent("MessageDisplay", False, ROLE_NONE, _UNREVIEWED),
)

BY_NAME: Dict[str, HookEvent] = {e.name: e for e in HOOK_REGISTRY}

COMMON_FIELDS: FrozenSet[str] = frozenset(
    {"session_id", "transcript_path", "cwd", "hook_event_name"}
)

PAYLOAD_EXTRAS: Dict[str, Dict[str, FrozenSet[str]]] = {
    "SessionStart": {
        "required": frozenset({"source"}),
        "optional": frozenset({"session_title", "agent_type", "model", "permission_mode"}),
    },
    "SessionEnd": {
        "required": frozenset({"reason"}),
        "optional": frozenset({"permission_mode"}),
    },
}



KNOWN_SUBSCRIBED = "known_subscribed"
KNOWN_UNSUBSCRIBED = "known_unsubscribed"
UNKNOWN_EVENT = "unknown_event"


@dataclass(frozen=True)
class HookClassification:

    event: str
    verdict: str
    role: str
    why: str
    missing_required: Tuple[str, ...] = ()
    unexpected_fields: Tuple[str, ...] = ()

    @property
    def actionable(self) -> bool:
        return self.verdict == KNOWN_SUBSCRIBED


def classify_payload(payload: Optional[dict]) -> HookClassification:
    if not isinstance(payload, dict):
        return HookClassification(
            event="", verdict=UNKNOWN_EVENT, role=ROLE_NONE,
            why="payload was not an object",
        )
    name = str(payload.get("hook_event_name") or "")
    known = BY_NAME.get(name)
    if known is None:
        return HookClassification(
            event=name, verdict=UNKNOWN_EVENT, role=ROLE_NONE,
            why=(
                f"not in the {MEASURED_AGAINST_VERSION} event set measured "
                f"{MEASURED_ON} - either a newer Claude Code or a typo in a "
                f"hand-edited settings file. Surfaced, never silently dropped"
            ),
        )
    extras = PAYLOAD_EXTRAS.get(name, {})
    required = extras.get("required", frozenset())
    optional = extras.get("optional", frozenset())
    present = set(payload)
    missing = tuple(sorted(required - present))
    unexpected = tuple(sorted(present - COMMON_FIELDS - required - optional))
    return HookClassification(
        event=name,
        verdict=KNOWN_SUBSCRIBED if known.subscribed else KNOWN_UNSUBSCRIBED,
        role=known.role,
        why=known.why,
        missing_required=missing,
        unexpected_fields=unexpected,
    )


@dataclass(frozen=True)
class EventSetDiff:

    added: Tuple[str, ...]
    removed: Tuple[str, ...]

    @property
    def drifted(self) -> bool:
        return bool(self.added or self.removed)

    def summary(self) -> str:
        if not self.drifted:
            return (
                f"event set matches the contract measured against "
                f"{MEASURED_AGAINST_VERSION}"
            )
        parts = []
        if self.added:
            parts.append(
                "NEW events this build ships that the contract does not "
                f"know: {', '.join(self.added)}"
            )
        if self.removed:
            parts.append(
                "events the contract expects that this build does NOT ship: "
                f"{', '.join(self.removed)} - any state fed only by these is "
                "now UNREACHABLE while still looking implemented"
            )
        return "; ".join(parts)


def diff_event_set(observed: Optional[Sequence[str]]) -> Optional[EventSetDiff]:
    """Compare a live Claude's event list against this contract.

    Description: the "check future shapes" half. ``removed`` is the
      dangerous direction and the reason this exists: a subscription to
      an event that no longer fires does not error, it simply never
      arrives, and every state it fed becomes permanently unreachable
      while the code that reads it still looks complete.

      Returns None - CANNOT DETERMINE - when handed nothing. An empty or
      unreadable observation is not "the build ships no hooks"; it is a
      failed measurement, and reporting it as total removal would be a
      false alarm on every event at once.
    Inputs: observed (sequence[str] | None) - event names read from a
      live build.
    Output: EventSetDiff | None.
    Example: diff_event_set(ALL_HOOK_EVENTS).drifted -> False
    """
    if not observed:
        return None
    seen = set(observed)
    mine = set(ALL_HOOK_EVENTS)
    return EventSetDiff(
        added=tuple(sorted(seen - mine)),
        removed=tuple(sorted(mine - seen)),
    )


def unreviewed_events() -> Tuple[str, ...]:
    return tuple(e.name for e in HOOK_REGISTRY if e.why == _UNREVIEWED)
