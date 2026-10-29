
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from src.cplugs.huddle import kinds, review

OVERRIDE_FIELD = "not_a_question"

NOT_A_QUESTION_SCHEMA = {OVERRIDE_FIELD: {"type": "boolean", "description": "reply only. true when an info or answer ends in a question mark but is NOT a question to the owner (a quoted title, a rhetorical line). Default false."}}

REPLY_REFUSAL = "questions go in task_manager_ask with `questions`; an info is never answered (task_manager_guide topic: 5)"
ASK_REFUSAL = "several questions in one plain text: pass them as `questions` (a list) so each is answered on its own (task_manager_guide topic: 5)"

MAX_PLAIN_QUESTION_MARKS = 1
MIN_NUMBERED_QUESTIONS = 2

_TRAILING = " \t*_`\"')]"
_NUMBERED = re.compile(r"^\s*\d+[.)]\s")

RETIRED_LOOK_ACTIONS = {
    review.ANSWER: "a look cannot ask for an answer: use task_manager_ask with a typed question (it works from the collapsed row)",
    review.TICK: "a look cannot ask for a tick: use task_manager_update with state review and review_action tick",
    review.PUSH: "a look cannot ask for a push: use task_manager_update with state review and review_action push",
}

QUESTION_REASON = "a question reaches the owner"
ANSWER_REASON = "an answer to the owner's own message reaches him in any state until he reads it"
REVIEW_REASON = "setting review reaches the owner"
NOTIFY_REASON = "an info with notify marks the item unread and badges the tab, but asks nothing; to ask use task_manager_ask, to hand over work set state review"
_NOT_REACHING = "post a question (task_manager_ask), set review (task_manager_update state review), or add notify true to an info"


def _ends_question(line: str) -> bool:
    return line.rstrip(_TRAILING).endswith("?")


def reads_like_question(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    if _ends_question(lines[-1]):
        return True
    numbered = sum(1 for ln in lines if _NUMBERED.match(ln) and _ends_question(ln))
    return numbered >= MIN_NUMBERED_QUESTIONS


def check_reply(kind: Optional[str], args: Mapping[str, Any]) -> Optional[str]:
    if args.get(OVERRIDE_FIELD) is True:
        return None
    if (kind is None or kind in kinds.INFO_KINDS) and reads_like_question(args.get("text")):
        return REPLY_REFUSAL
    return None


def check_ask(args: Mapping[str, Any]) -> Optional[str]:
    text = args.get("text")
    if args.get("questions") is None and isinstance(text, str) and text.count("?") > MAX_PLAIN_QUESTION_MARKS:
        return ASK_REFUSAL
    return None


def fields(owner: bool, reason: str) -> Dict[str, Any]:
    return {"reaches_owner": owner, "reaches_owner_reason": reason}


def not_reaching(status: Any = None) -> Dict[str, Any]:
    if status == "working":
        return fields(False, f"item is working and folded; {_NOT_REACHING}")
    return fields(False, f"nothing here is actionable; {_NOT_REACHING}")


def for_reply(notify: bool, status: Any = None, kind: Any = None) -> Dict[str, Any]:
    if kind == "answer":
        return fields(True, ANSWER_REASON)
    if notify:
        return fields(False, NOTIFY_REASON)
    return not_reaching(status)


def for_update(args: Mapping[str, Any], status: Any = None) -> Dict[str, Any]:
    if args.get("state") == "review" or any(args.get(f) for f in review.FIELDS):
        return fields(True, REVIEW_REASON)
    return not_reaching(status)


def merge(payload: Dict[str, Any], steer: Mapping[str, Any]) -> Dict[str, Any]:
    return {**payload, **steer}
