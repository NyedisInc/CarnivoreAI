
from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Dict, List

from src.core.deepsearch import constants as K

SUGGEST_MIN_CHARS: int = 2
SUGGEST_MAX_CHARS: int = 64
SUGGEST_LIMIT_DEFAULT: int = 8
SUGGEST_LIMIT_MAX: int = 20
VOCAB_TABLE: str = "temp.session_search_vocab"


class InvalidPrefix(ValueError):
    pass


def normalize_prefix(raw: str) -> str:
    prefix = unicodedata.normalize("NFKC", raw.strip()).lower()
    if not SUGGEST_MIN_CHARS <= len(prefix) <= SUGGEST_MAX_CHARS:
        raise InvalidPrefix(f"prefix must be {SUGGEST_MIN_CHARS} to {SUGGEST_MAX_CHARS} characters")
    return prefix


def _upper_bound(prefix: str) -> str:
    return prefix[:-1] + chr(ord(prefix[-1]) + 1) if ord(prefix[-1]) < 0x10FFFF else prefix + "\U0010ffff"


def suggest_terms(conn: sqlite3.Connection, raw_prefix: str, limit: int = SUGGEST_LIMIT_DEFAULT) -> Dict[str, Any]:
    prefix = normalize_prefix(raw_prefix)
    capped = max(1, min(int(limit), SUGGEST_LIMIT_MAX))
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {VOCAB_TABLE} USING fts5vocab(main, {K.FTS_TABLE}, 'row')")
    rows = conn.execute(f"SELECT term, doc FROM {VOCAB_TABLE} WHERE term >= ? AND term < ? "
                        "ORDER BY doc DESC, term ASC LIMIT ?", (prefix, _upper_bound(prefix), capped)).fetchall()
    terms: List[Dict[str, Any]] = [{"term": r[0], "docs": int(r[1])} for r in rows]
    return {"prefix": prefix, "count": len(terms), "terms": terms}
