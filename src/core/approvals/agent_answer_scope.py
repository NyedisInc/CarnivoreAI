"""Which agent dialog answers the beast mode grid's ``agent_writes`` row may approve on its own: a plain yes or no on a permission prompt.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping, Optional

from src.core.approvals.extract import KIND_ASK, KIND_PLAN
from src.core.approvals.plain_answer import APPROVABLE_KINDS, PLAIN_NO, PLAIN_YES, plain_no_label, plain_yes_label

HELD_UNREADABLE: str = "unreadable"
HELD_STARTUP: str = "other_startup"
HELD_QUESTION: str = "questions"
HELD_PLAN: str = "plan_approval"
HELD_FREE_TEXT: str = "free_text"
HELD_WIDENING: str = "widening_yes"


def _as_dialog(shown: Mapping[str, Any]) -> Optional[SimpleNamespace]:
    options = shown.get("options")
    tabs = shown.get("tabs") or ()
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options) or not isinstance(tabs, (list, tuple)):
        return None
    return SimpleNamespace(kind=shown.get("kind"), multi_select=shown.get("multi_select") is not False, tabs=tuple(tabs),
                           options=tuple(options))


def held_reason(shown: Any, choice: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(shown, Mapping):
        return HELD_UNREADABLE
    if shown.get("startup_kind") is not None:
        return HELD_STARTUP
    kind = shown.get("kind")
    if kind == KIND_ASK:
        return HELD_QUESTION
    if kind == KIND_PLAN:
        return HELD_PLAN
    if kind not in APPROVABLE_KINDS:
        return HELD_STARTUP
    dialog = _as_dialog(shown)
    if dialog is None:
        return HELD_UNREADABLE
    if dialog.multi_select or dialog.tabs:
        return HELD_QUESTION
    if not isinstance(choice, Mapping):
        return HELD_QUESTION
    if choice.get("other") is not None:
        return HELD_FREE_TEXT
    yes, no = plain_yes_label(dialog), plain_no_label(dialog)
    plain = choice.get("plain")
    if plain is not None:
        return None if (plain == PLAIN_YES and yes) or (plain == PLAIN_NO and no) else HELD_WIDENING
    option = choice.get("option")
    if isinstance(option, str) and option in {label for label in (yes, no) if label}:
        return None
    return HELD_WIDENING
