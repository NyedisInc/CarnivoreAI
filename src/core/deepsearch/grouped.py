
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from src.core.stream_redactor import redact_whole
from src.core.deepsearch.query import match_expression, tokens_of
from src.core.deepsearch import constants as K
from src.core.deepsearch import hit_bookmarks, hit_exports, vault_lane
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch.peer_air_gap import PeerGate
from src.core.deepsearch.search import CONVERSATION_EXPR, HIT_SQL, HitOpener, hit_of

GROUP_LIMIT_DEFAULT: int = 20
GROUP_LIMIT_MAX: int = 50
PER_GROUP_DEFAULT: int = 3
PER_GROUP_MAX: int = 10
KINDS: Tuple[str, ...] = (K.KIND_USER, K.KIND_ASSISTANT, K.KIND_TOOL, K.KIND_SUMMARY)
FIRST_PROMPT_CHARS: int = 160
_BATCH: int = 500

_AGGREGATE_SQL = (
    f"WITH m AS MATERIALIZED (SELECT {K.FTS_TABLE}.rowid AS id, bm25({K.FTS_TABLE}) AS b FROM {K.FTS_TABLE} "
    f"WHERE {K.FTS_TABLE} MATCH ?) "
    f"SELECT {CONVERSATION_EXPR} AS conversation_id, r.kind, COALESCE(l.file_kind, ?) AS file_kind, "
    "COUNT(*) AS n, MIN(m.b) AS best "
    f"FROM m JOIN {K.ROWS_TABLE} AS r ON r.id = m.id "
    f"JOIN {K.LIVE_TABLE} AS l ON l.id = r.{K.LIVE_ID_COLUMN} "
    "WHERE 1 = 1"
)


class InvalidKinds(ValueError):
    pass


def check_kinds(kinds: Optional[Iterable[str]]) -> Optional[Tuple[str, ...]]:
    if not kinds:
        return None
    wanted = tuple(sorted(set(kinds)))
    bad = [k for k in wanted if k not in KINDS]
    if bad:
        raise InvalidKinds(f"unknown kinds {bad}; one of {list(KINDS)}")
    return wanted


def _kinds_clause(kinds: Optional[Sequence[str]]) -> Tuple[str, List[Any]]:
    if not kinds:
        return "", []
    return f" AND r.kind IN ({', '.join('?' for _ in kinds)})", list(kinds)


def _aggregate(conn: sqlite3.Connection, expr: str, kinds: Optional[Sequence[str]],
               conversation_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
    clause, params = _kinds_clause(kinds)
    sql = _AGGREGATE_SQL + clause
    args: List[Any] = [expr, K.FILE_CONVERSATION, *params]
    if conversation_id:
        sql += f" AND {CONVERSATION_EXPR} = ?"
        args.append(conversation_id)
    sql += " GROUP BY 1, 2, 3"
    groups: Dict[str, Dict[str, Any]] = {}
    for conv, kind, file_kind, n, best in conn.execute(sql, args):
        g = groups.setdefault(conv, {"conversation_id": conv, "matches": 0, "by_kind": {}, "by_file_kind": {},
                                     "best": None, "best_said": None})
        g["matches"] += int(n)
        g["by_kind"][kind] = g["by_kind"].get(kind, 0) + int(n)
        g["by_file_kind"][file_kind] = g["by_file_kind"].get(file_kind, 0) + int(n)
        g["best"] = best if g["best"] is None else min(g["best"], best)
        if kind != K.KIND_TOOL:
            g["best_said"] = best if g["best_said"] is None else min(g["best_said"], best)
    return groups


def _batches(items: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), _BATCH):
        yield items[start:start + _BATCH]


def _iso_from_ns(value: Optional[int]) -> Optional[str]:
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1e9, tz=timezone.utc).isoformat()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    try:
        conn.execute(f"SELECT 1 FROM {name} LIMIT 0")
    except sqlite3.OperationalError:
        return False
    return True


def describe(conn: sqlite3.Connection, conversation_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    from src.core.transcript_manifest import constants as TM

    out: Dict[str, Dict[str, Any]] = {c: {"session_uuid": None, "session": None, "project_id": None, "project": None,
                                          "first_prompt": None, "working_dir": None, "last_active": None,
                                          "family": None} for c in conversation_ids}
    ids = list(out)

    def fill(conv: str, **values: Any) -> None:
        row = out[conv]
        for key, value in values.items():
            if row.get(key) in (None, "") and value not in (None, ""):
                row[key] = value

    for chunk in _batches(ids):
        marks = ", ".join("?" for _ in chunk)
        if _has_table(conn, "conversation_index"):
            for conv, uuid, pid, pname, sname, prompt, wd, family in conn.execute(
                    "SELECT conversation_id, session_uuid, project_id, project_name, session_name, first_prompt, "
                    f"working_dir, agent_family FROM conversation_index WHERE conversation_id IN ({marks})", chunk):
                fill(conv, session_uuid=uuid, project_id=pid, project=pname, session=sname,
                     first_prompt=redact_whole(prompt or "")[:FIRST_PROMPT_CHARS], working_dir=wd, family=family)
        if _has_table(conn, "sessions"):
            for conv, uuid, pid, name, wd, family in conn.execute(
                    "SELECT claude_session_uuid, session_uuid, project_id, COALESCE(NULLIF(title, ''), "
                    "NULLIF(claude_title, ''), tmux_name), working_dir, agent_family FROM sessions "
                    f"WHERE claude_session_uuid IN ({marks}) ORDER BY id DESC", chunk):
                fill(conv, session_uuid=uuid, project_id=pid, session=name, working_dir=wd, family=family)
        if _has_table(conn, "lineage_edges") and _has_table(conn, "sessions"):
            for conv, uuid, pid, name, wd, family in conn.execute(
                    "SELECT e.parent_id, s.session_uuid, s.project_id, COALESCE(NULLIF(s.title, ''), "
                    "NULLIF(s.claude_title, ''), s.tmux_name), s.working_dir, s.agent_family FROM lineage_edges e "
                    "JOIN sessions s ON s.session_uuid = e.child_id WHERE e.parent_type = 'conversation' "
                    f"AND e.child_type = 'session' AND e.parent_id IN ({marks}) ORDER BY e.created_at DESC", chunk):
                fill(conv, session_uuid=uuid, project_id=pid, session=name, working_dir=wd, family=family)
        if _has_table(conn, TM.TABLE):
            for conv, mtime, family in conn.execute(
                    f"SELECT conversation_id, MAX(mtime_ns), MAX(family) FROM {TM.TABLE} "
                    f"WHERE conversation_id IN ({marks}) GROUP BY conversation_id", chunk):
                fill(conv, last_active=_iso_from_ns(mtime), family=family)
    for conv, backed in vault_lane.described(ids).items():
        fill(conv, session_uuid=backed.session_uuid, session=backed.title, project=backed.project_name,
             working_dir=backed.working_dir, family=backed.family)
    missing = sorted({r["project_id"] for r in out.values() if r["project_id"] is not None and not r["project"]})
    if missing and _has_table(conn, "projects"):
        names = dict(conn.execute(f"SELECT id, display_name FROM projects WHERE id IN "
                                  f"({', '.join('?' for _ in missing)})", missing).fetchall())
        for row in out.values():
            if row["project_id"] in names and not row["project"]:
                row["project"] = names[row["project_id"]]
    return out


def _matches_project(meta: Dict[str, Any], project: Optional[str]) -> bool:
    if not project:
        return True
    return (str(meta.get("project") or "").lower() == project.lower()
            or (meta.get("project_id") is not None and str(meta["project_id"]) == project))


def _rank_key(group: Dict[str, Any]) -> Tuple[int, float, int]:
    said = group["best_said"]
    return (0, float(said), -group["matches"]) if said is not None else (1, float(group["best"]), -group["matches"])


def _open_hits(conn: sqlite3.Connection, opener: HitOpener, expr: str, tokens: List[str], conversations: Sequence[str],
               kinds: Optional[Sequence[str]], per_group: int) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    hits: Dict[str, List[Dict[str, Any]]] = {c: [] for c in conversations}
    tried: Dict[str, int] = {c: 0 for c in conversations}
    stale: List[str] = []
    clause, params = _kinds_clause(kinds)
    for chunk in _batches(list(conversations)):
        sql = (HIT_SQL + clause + f" AND {CONVERSATION_EXPR} IN ({', '.join('?' for _ in chunk)}) "
               f"ORDER BY conversation_id, (r.kind = '{K.KIND_TOOL}'), rank, r.line")
        for row in conn.execute(sql, [expr, *params, *chunk]):
            conv = row["conversation_id"]
            if len(hits[conv]) >= per_group or tried[conv] >= per_group * 4:
                continue
            tried[conv] += 1
            opened = opener.open_with_time(row, tokens)
            if opened is None:
                if conv not in stale:
                    stale.append(conv)
                continue
            hits[conv].append(hit_of(row, *opened))
    return hits, stale


@contextmanager
def _read_snapshot(conn: sqlite3.Connection, wanted: bool) -> Iterator[None]:
    if not wanted or conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        if conn.in_transaction:
            conn.execute("COMMIT")


def search_grouped(conn: sqlite3.Connection, state_dir: Path, query: str, *, kinds: Optional[Iterable[str]] = None,
                   project: Optional[str] = None, conversation_id: Optional[str] = None,
                   limit: int = GROUP_LIMIT_DEFAULT, offset: int = 0, per_group: int = PER_GROUP_DEFAULT,
                   overrides: Optional[Dict[str, Any]] = None, peer_gate: Optional[PeerGate] = None) -> Dict[str, Any]:
    wanted = check_kinds(kinds)
    tokens = tokens_of(query)
    expr = match_expression(query)
    page = max(1, min(int(limit), GROUP_LIMIT_MAX))
    per = max(1, min(int(per_group), PER_GROUP_MAX))
    start = max(0, int(offset))
    answer: Dict[str, Any] = {"query": query, "tokens": tokens, "kinds": list(wanted or KINDS),
                              "total_conversations": 0, "total_matches": 0, "offset": start, "count": 0,
                              "groups": [], "stale": [], "frames_read": 0, "live_bytes_read": 0}
    if expr is None:
        return answer
    with _read_snapshot(conn, peer_gate is not None and peer_gate.active):
        groups = _aggregate(conn, expr, wanted, conversation_id)
        meta = describe(conn, sorted(groups))
        if peer_gate is not None and peer_gate.active:
            allowed = peer_gate.admitted(conn, meta)
            groups = {c: g for c, g in groups.items() if c in allowed}
        ranked = sorted((g for c, g in groups.items() if _matches_project(meta[c], project)), key=_rank_key)
        chosen = ranked[start:start + page]
        opener = HitOpener(rules_mod.read_overrides() if overrides is None else overrides)
        hits, stale = _open_hits(conn, opener, expr, tokens, [g["conversation_id"] for g in chosen], wanted, per)
        out = []
        for g in chosen:
            conv = g["conversation_id"]
            out.append({"conversation_id": conv, "matches": g["matches"], "by_kind": g["by_kind"],
                        "by_file_kind": g["by_file_kind"], **meta[conv], "hits": hits[conv]})
        hit_bookmarks.attach(state_dir, out)
        hit_exports.attach(conn, out)
        answer.update(total_conversations=len(ranked), total_matches=sum(g["matches"] for g in ranked),
                      count=len(out), groups=out, stale=stale, frames_read=opener.frames_read,
                      live_bytes_read=opener.live_bytes_read)
    return answer
