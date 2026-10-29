
from __future__ import annotations

from datetime import datetime, timezone

CHALLENGE = ("this was parked on {what} and was due to clear by {by}. it has not. is it still blocked, and by what exactly? can you do that part "
             "yourself? then pick one: clear it (set review, or open and keep working), extend it once (task_manager_update state waiting again with "
             "extend_reason and a new expect_by; a second extension is refused), or ask the owner with task_manager_ask.")
CLEARED = "cleared: {what}"
FAILED = "wait failed: {reason}"
ESCALATION = "stuck on {what} past two deadlines (it was due {by})."
STUCK_PROMPT = "this task waited on {what} since {since}. what now?"
NO_REASON = "no reason given"


def when(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def challenge(what: str, expect_by: float) -> str:
    return CHALLENGE.format(what=what or "something", by=when(expect_by))


def cleared(what: str) -> str:
    return CLEARED.format(what=what)


def failed(reason: str) -> str:
    return FAILED.format(reason=reason or NO_REASON)


def escalation(what: str, expect_by: float) -> str:
    return ESCALATION.format(what=what or "something", by=when(expect_by))


def stuck_prompt(what: str, set_at: float) -> str:
    return STUCK_PROMPT.format(what=what or "something", since=when(set_at))
