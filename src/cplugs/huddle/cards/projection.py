
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from src.cplugs.huddle import rules
from src.cplugs.huddle.cards.columns import CHAT_KINDS

TODO, IN_PROGRESS, REVIEW, DONE = "todo", "in_progress", "review", "done"

_REVIEW_STATES = (rules.REVIEW, rules.WAITING)


def card_shaped(row: Mapping[str, Any]) -> bool:
    return not row["deleted"] and row["swarm_ref"] == "" and row["kind"] not in CHAT_KINDS


def _committed(row: Mapping[str, Any]) -> bool:
    try:
        return bool(row["card_queued"])
    except (KeyError, IndexError):
        return False


def column(row: Mapping[str, Any]) -> str:
    state = row["state"]
    if state in rules.APPROVED_STATES:
        return DONE
    if state in _REVIEW_STATES:
        accepted = row["card_parent"] is not None and row["card_accepted_at"] is not None
        return DONE if accepted else REVIEW
    if state == rules.OPEN and (row["card_holder"] is not None or row["claude_working"] or _committed(row)):
        return IN_PROGRESS
    return TODO


def queued(row: Mapping[str, Any]) -> bool:
    return column(row) == IN_PROGRESS and row["card_holder"] is None and not row["claude_working"]


def dealable(row: Mapping[str, Any]) -> bool:
    return (queued(row) and row["state"] == rules.OPEN and row["card_paused_mode"] == "" and row["card_archived_at"] is None
            and row["card_dealt_to"] is None and row["card_mark"] != "waiting_for_slot")


def waiting_lane(row: Mapping[str, Any]) -> Optional[str]:
    col = column(row)
    if col == TODO:
        return TODO
    return IN_PROGRESS if col == IN_PROGRESS and queued(row) else None


def queue_index(rows_in_list_order: Iterable[Mapping[str, Any]]) -> Dict[int, int]:
    places: Dict[int, int] = {}
    counts: Dict[str, int] = {}
    for row in rows_in_list_order:
        lane = waiting_lane(row)
        if lane is not None:
            counts[lane] = counts.get(lane, 0) + 1
            places[row["id"]] = counts[lane]
    return places


def _in(values: Iterable[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in sorted(values)) + ")"


COLUMN_SQL = (
    f"CASE WHEN state IN {_in(rules.APPROVED_STATES)} THEN '{DONE}' "
    f"WHEN state IN {_in(_REVIEW_STATES)} THEN "
    f"CASE WHEN card_parent IS NOT NULL AND card_accepted_at IS NOT NULL THEN '{DONE}' ELSE '{REVIEW}' END "
    f"WHEN state = '{rules.OPEN}' AND (card_holder IS NOT NULL OR COALESCE(claude_working, 0) != 0 OR card_queued != 0) THEN '{IN_PROGRESS}' "
    f"ELSE '{TODO}' END"
)
