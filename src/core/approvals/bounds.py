
from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional

import structlog
from pydantic import ValidationError

from src.models.dialogs import ApprovalItem

logger = structlog.get_logger()

_LOGGED_DROPS: set = set()
_LOGGED_DROPS_MAX: int = 1000

CUT_MARKER: str = "..."
SUMMARY_MAX: int = 1000


def fit_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:max(limit - len(CUT_MARKER), 0)] + CUT_MARKER[:limit]


def one_line(text: str) -> str:
    return " ".join("".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text).split())


def _limit(field: Any) -> Optional[int]:
    for meta in field.metadata:
        if hasattr(meta, "max_length"):
            return meta.max_length
    return None


_CUT_TEXT = ("summary", "question")
_CUT_LISTS = ("options", "rows", "tabs")
_LIMITS: Dict[str, int] = {name: lim for name, f in ApprovalItem.model_fields.items()
                           if name in _CUT_TEXT + _CUT_LISTS and (lim := _limit(f)) is not None}


def _log_cut(item_id: str, field: str, kept: int, dropped: int) -> None:
    key = ("cut", item_id[:80], field)
    if key in _LOGGED_DROPS:
        return
    if len(_LOGGED_DROPS) >= _LOGGED_DROPS_MAX:
        _LOGGED_DROPS.clear()
    _LOGGED_DROPS.add(key)
    logger.warning("approvals_list_cut", item_id=key[1], field=field, kept=kept, dropped=dropped)


def bound_item(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    for name, limit in _LIMITS.items():
        value = out.get(name)
        if isinstance(value, str):
            out[name] = fit_text(value, limit)
        elif isinstance(value, list) and len(value) > limit:
            out[name] = value[:limit]
            _log_cut(str(item.get("id")), name, limit, len(value) - limit)
    return out


def valid_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for raw in items:
        item = bound_item(raw)
        try:
            ApprovalItem.model_validate(item)
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
            key = (str(item.get("id"))[:80], tuple(fields))
            if key not in _LOGGED_DROPS:
                if len(_LOGGED_DROPS) >= _LOGGED_DROPS_MAX:
                    _LOGGED_DROPS.clear()
                _LOGGED_DROPS.add(key)
                logger.error("approvals_item_dropped", item_id=key[0], source=str(item.get("source"))[:32], fields=fields)
            continue
        kept.append(item)
    return kept
