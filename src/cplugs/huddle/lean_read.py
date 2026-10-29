
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple, Union

from src.cplugs.huddle import review, review_checks, rules
from src.cplugs.huddle import github_issue, item_marker, item_owner, title as titles
from src.cplugs.huddle.rules import TaskManagerInvalid

LEAD_MAX = 120

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

ITEM_THREAD_TAIL = 10

FULL = "full"

_OPTIONAL_SUMMARY = ("group", "needs_action", "forked_from", "from_project", "review_action", item_marker.FIELD, github_issue.FIELD,
                     item_owner.FIELD)

EXTRA_FIELDS = frozenset({"text", "note", "thread", "review", "state", "kind", "revision", "created_by", "list",
                          "needs_you", "start_trigger", "forked_from_title", "deleted"})


def lead(text: Any, limit: int = LEAD_MAX) -> str:
    first = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def fork_row(fork: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": fork["id"], "title": fork.get(titles.FIELD) or lead(fork.get("text")), "status": fork["status"], "list": fork["list"],
            "owner": fork.get(item_owner.TAGGED_BY) or fork["created_by"]}


def parse_fields(raw: Any, thread: bool = False) -> Union[str, FrozenSet[str]]:
    if raw is None or raw == "":
        names: List[str] = []
    elif isinstance(raw, str):
        names = [n.strip() for n in raw.split(",") if n.strip()]
    elif isinstance(raw, (list, tuple)) and all(isinstance(n, str) for n in raw):
        names = [n.strip() for n in raw if n.strip()]
    else:
        raise TaskManagerInvalid("fields is a list of names (or 'full'): " + ", ".join(sorted(EXTRA_FIELDS)))
    if FULL in names:
        return FULL
    names = ["review" if n in review.FIELDS else n for n in names]
    unknown = sorted(set(names) - EXTRA_FIELDS)
    if unknown:
        raise TaskManagerInvalid(f"unknown field(s): {', '.join(unknown)}; allowed: full, " + ", ".join(sorted(EXTRA_FIELDS)))
    return frozenset(names) | ({"thread"} if thread else set())


def summary_row(item: Dict[str, Any], want: Iterable[str] = ()) -> Dict[str, Any]:
    names = set(want)
    out: Dict[str, Any] = {"id": item["id"], "number": item.get("number"), "status": item.get("status"),
                           "section": item.get("section"), "unread": bool(item.get("unread"))}
    headline = item.get(titles.FIELD) or ("" if "text" in names else lead(item.get("text")))
    if headline:
        out[titles.FIELD] = headline
    out.update({k: item[k] for k in _OPTIONAL_SUMMARY if item.get(k)})
    for name in sorted(names):
        keys = (*review.FIELDS, review_checks.FIELD) if name == "review" else (name,)
        out.update({k: item[k] for k in keys if k in item and k not in out})
    return out


def project(item: Dict[str, Any], fields: Union[str, FrozenSet[str]]) -> Dict[str, Any]:
    return item if fields == FULL else summary_row(item, fields)


def hides(item: Dict[str, Any], include_approved: bool) -> bool:
    return not include_approved and item.get("state") in rules.APPROVED_STATES


def page_of(rows: List[Any], limit: Any, cursor: Any) -> Tuple[List[Any], Optional[str]]:
    size = DEFAULT_LIMIT if limit is None else _whole(limit, "limit", 1, MAX_LIMIT)
    start = 0 if cursor in (None, "") else _whole(cursor, "cursor", 0, None)
    end = start + size
    return rows[start:end], (str(end) if end < len(rows) else None)


def _whole(value: Any, name: str, low: int, high: Optional[int]) -> int:
    try:
        number = int(value) if not isinstance(value, bool) else -1
    except (TypeError, ValueError):
        number = low - 1
    if number < low or (high is not None and number > high):
        raise TaskManagerInvalid(f"{name} must be a whole number" + (f" from {low} to {high}" if high else f" of {low} or more"))
    return number
