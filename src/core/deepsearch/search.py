
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.deepsearch.query import match_expression, tokens_of
from src.core.transcript_source import constants as TS
from src.core.deepsearch import constants as K
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch.byte_source import SourceCache, is_vault_mark
from src.core.deepsearch.extract import extract, record_identity
from src.core.deepsearch.live.indexer import rules_for
from src.core.deepsearch.live.reader import read_line
from src.core.deepsearch.live.watermark import line_holds

logger = structlog.get_logger()

CONVERSATION_EXPR = "l.conversation_id"

HIT_SQL = (
    f"SELECT r.id, {CONVERSATION_EXPR} AS conversation_id, r.frame_index, r.frame_offset, r.frame_len, "
    "r.frame_first_line, r.line, r.kind, "
    f"bm25({K.FTS_TABLE}) AS rank, c.project_name, c.session_name, c.project_id, c.session_uuid, "
    f"r.{K.LIVE_ID_COLUMN} AS live_id, l.path AS live_path, l.family AS live_family, l.file_kind AS live_kind, "
    "l.last_serial AS live_serial, l.last_serial_offset AS live_serial_offset, l.indexed_offset AS live_end, "
    "l.base_point_id AS live_mark "
    f"FROM {K.FTS_TABLE} JOIN {K.ROWS_TABLE} AS r ON r.id = {K.FTS_TABLE}.rowid "
    f"JOIN {K.LIVE_TABLE} AS l ON l.id = r.{K.LIVE_ID_COLUMN} "
    f"LEFT JOIN conversation_index AS c ON c.conversation_id = {CONVERSATION_EXPR} "
    f"WHERE {K.FTS_TABLE} MATCH ?"
)


def snippet(text: str, tokens: List[str]) -> str:
    if not tokens:
        return text[: K.SNIPPET_BEFORE + K.SNIPPET_AFTER]
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")\w*", re.IGNORECASE | re.UNICODE)
    first = pattern.search(text)
    at = first.start() if first else 0
    start = max(0, at - K.SNIPPET_BEFORE)
    end = min(len(text), at + K.SNIPPET_AFTER)
    window = pattern.sub(lambda m: f"{TS.MARK_OPEN}{m.group(0)}{TS.MARK_CLOSE}", text[start:end])
    window = " ".join(window.split())
    return (TS.SNIPPET_ELLIPSIS if start else "") + window + (TS.SNIPPET_ELLIPSIS if end < len(text) else "")


class HitOpener:
    """Opens hits for one search: one live-file check per file, one line read per hit.

    A row's bytes come from the file on disk, or (a row marked ``vault``) from the backup vault: ``byte_source.open_source``.
    A source that cannot be opened or read makes its hits STALE (dropped and named in ``stale``), never an error.
    """

    def __init__(self, overrides: Dict[str, Any]) -> None:
        self._overrides = overrides
        self._live_ok: Dict[int, bool] = {}
        self._sources = SourceCache()
        self.frames_read = 0
        self.packed_bytes_read = 0
        self.live_bytes_read = 0

    def _source(self, row: sqlite3.Row):
        return self._sources.get(int(row["live_id"]), row["live_path"], row["live_mark"], row["conversation_id"],
                                 row["live_kind"] or K.FILE_CONVERSATION)

    def _live_holds(self, row: sqlite3.Row) -> bool:
        live_id = int(row["live_id"])
        if live_id not in self._live_ok:
            try:
                ok, read = line_holds(self._source(row), row["live_serial_offset"], row["live_end"], row["live_serial"])
                self.live_bytes_read += read
            except OSError as exc:
                if is_vault_mark(row["live_mark"]):
                    logger.warning("search_index_vault_unreadable", conversation_id=row["conversation_id"], error=str(exc)[:200])
                ok = False
            self._live_ok[live_id] = ok
        return self._live_ok[live_id]

    def _open_live(self, row: sqlite3.Row, tokens: List[str]) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        if not self._live_holds(row):
            return None
        try:
            raw = read_line(self._source(row), row["frame_offset"], row["frame_len"])
        except OSError as exc:
            logger.warning("search_index_live_open_failed", conversation_id=row["conversation_id"], error=str(exc))
            return None
        self.live_bytes_read += len(raw)
        if len(raw) != row["frame_len"] or not raw.endswith(b"\n"):
            return None
        family = row["live_family"] or "claude"
        found = extract(raw, rules_for(self._overrides, family, row["live_kind"]), family)
        if not found:
            return ("", None, None)
        stamp, uuid = record_identity(raw)
        return (snippet(found[1], tokens), stamp, uuid)

    def open(self, row: sqlite3.Row, tokens: List[str]) -> Optional[str]:
        """The hit's snippet, or None when its live file no longer holds the indexed bytes."""
        opened = self._open_live(row, tokens)
        return opened[0] if opened else None

    def open_with_time(self, row: sqlite3.Row,
                       tokens: List[str]) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """The hit's (snippet, timestamp, message uuid), or None when its live file no longer holds the indexed bytes."""
        return self._open_live(row, tokens)


def hit_of(row: sqlite3.Row, text: str, at: Optional[str] = None, entry_uuid: Optional[str] = None) -> Dict[str, Any]:
    return {
        "conversation_id": row["conversation_id"], "session_uuid": row["session_uuid"],
        "project_id": row["project_id"], "project": row["project_name"], "session": row["session_name"],
        "point_id": None, "frame_index": row["frame_index"], "frame_offset": row["frame_offset"],
        "line": row["line"], "kind": row["kind"], "snippet": text, "score": -float(row["rank"]),
        "index": "body", "live": True, "file_kind": row["live_kind"] or K.FILE_CONVERSATION, "at": at,
        "entry_uuid": entry_uuid, "from_backup": is_vault_mark(row["live_mark"]),
    }


def search(conn: sqlite3.Connection, state_dir: Path, query: str, *, conversation_id: Optional[str] = None,
           project: Optional[str] = None, limit: int = K.SEARCH_LIMIT_DEFAULT,
           overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tokens = tokens_of(query)
    expr = match_expression(query)
    empty = {"query": query, "tokens": tokens, "count": 0, "hits": [], "stale": [], "frames_read": 0,
             "packed_bytes_read": 0, "live_bytes_read": 0}
    if expr is None:
        return empty
    capped = max(1, min(int(limit), K.SEARCH_LIMIT_MAX))
    sql, params = HIT_SQL, [expr]
    if conversation_id:
        sql += f" AND {CONVERSATION_EXPR} = ?"
        params.append(conversation_id)
    if project:
        sql += " AND (lower(c.project_name) = lower(?) OR CAST(c.project_id AS TEXT) = ?)"
        params += [project, project]
    sql += " ORDER BY rank, conversation_id, r.line LIMIT ?"
    params.append(capped * 2)
    opener = HitOpener(rules_mod.read_overrides() if overrides is None else overrides)
    hits: List[Dict[str, Any]] = []
    stale: List[str] = []
    for row in conn.execute(sql, params):
        if len(hits) >= capped:
            break
        opened = opener.open_with_time(row, tokens)
        if opened is None:
            if row["conversation_id"] not in stale:
                stale.append(row["conversation_id"])
            continue
        hits.append(hit_of(row, *opened))
    if stale:
        logger.info("search_index_stale_hits", conversations=len(stale))
    return {**empty, "count": len(hits), "hits": hits, "stale": stale, "frames_read": opener.frames_read,
            "packed_bytes_read": opener.packed_bytes_read, "live_bytes_read": opener.live_bytes_read}


def merge_into(summary_answer: Dict[str, Any], body_answer: Dict[str, Any]) -> Dict[str, Any]:
    hits = [{**hit, "index": "conversation"} for hit in summary_answer["hits"]]
    seen = {hit["conversation_id"] for hit in hits}
    for hit in body_answer["hits"]:
        if hit["conversation_id"] not in seen:
            seen.add(hit["conversation_id"])
            hits.append({**hit, "source": "body"})
    return {**summary_answer, "count": len(hits), "hits": hits, "stale": body_answer["stale"],
            "frames_read": body_answer["frames_read"]}
