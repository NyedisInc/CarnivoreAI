
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import structlog

from src.cplugs.sdk.activity import ActivityUnavailable

logger = structlog.get_logger()

MAX_ROWS = 20000
_CROSSTALK_OPTIONAL = ("agent_sent", "spawn_task", "landed_session_id", "landed_at", "landed_header", "landed_anchor", "delivery_path",
                       "receiver_conversation_id", "receiver_record_uuid", "sender_conversation_id")
_CROSSTALK_BASE = ("id", "thread", "sender_id", "receiver_id", "sender_uuid", "receiver_uuid", "sender_name",
                   "receiver_name", "text", "in_reply_to", "expect_reply", "status", "created_at", "delivered_at", "source")
_SESSION_BASE = ("id", "session_uuid", "claude_session_uuid", "tmux_name", "title", "working_dir", "project_id", "origin",
                 "agent_family", "created_at")
_SESSION_OPTIONAL = ("parent_session_id", "fork_kind")


def _ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ActivityUnavailable(f"{path.name} is absent")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise ActivityUnavailable(f"{path.name}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> frozenset:
    return frozenset(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))


def _marks(values: Sequence[Any]) -> str:
    return ",".join("?" * len(values))


class ActivityReader:
    """Read-only access to the run-reconstruction sources of one install.

    Inputs: state_dir (Path) - this install's state directory.
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)

    def _core(self) -> sqlite3.Connection:
        from src.core.db import db_path_for  # noqa: PLC0415

        return _ro(db_path_for(self._state_dir))

    def _huddle(self) -> sqlite3.Connection:
        return self._core()

    def sources(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"core": "ok", "huddle": "ok", "optional": {}}
        try:
            with closing(self._core()) as conn:
                out["optional"] = {
                    "crosstalk_columns": sorted(_columns(conn, "crosstalk_messages") & set(_CROSSTALK_OPTIONAL)),
                    "sessions_columns": sorted(_columns(conn, "sessions") & set(_SESSION_OPTIONAL)),
                    "spawn_links": bool(_columns(conn, "agent_spawn_links")),
                    "mcp_events": bool(_columns(conn, "mcp_events")),
                }
        except ActivityUnavailable as exc:
            out["core"] = str(exc)
        try:
            with closing(self._huddle()) as conn:
                out["optional"]["huddle_source_item"] = "source_item_id" in _columns(conn, "work_items")
                out["optional"]["write_actors"] = bool(_columns(conn, "work_write_actors"))
        except ActivityUnavailable as exc:
            out["huddle"] = str(exc)
        return out

    def huddle_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        with closing(self._huddle()) as conn:
            have = _columns(conn, "work_items")
            extra_item = "".join(f", {c}" for c in ("source_item_id", "title") if c in have)
            extra_item += ", substr(review_description,1,400) AS review_description" if "review_description" in have else ""
            item = conn.execute(f"SELECT id, list_key, text, created_by, state, created_at, updated_at{extra_item} FROM work_items WHERE id=?",
                                (item_id,)).fetchone()
            if item is None:
                return None
            msgs = conn.execute("SELECT id, author, author_key, kind, substr(text,1,400) AS text, created_at, seq FROM work_messages "
                                "WHERE item_id=? ORDER BY id LIMIT ?", (item_id, MAX_ROWS)).fetchall()
            ev_cols = _columns(conn, "work_card_events")
            extra = [c for c in sorted(ev_cols) if c not in {"id", "item_id", "list_key", "at", "kind", "from_col", "to_col", "by", "detail"}]
            events = conn.execute(f"SELECT id, at, kind, from_col, to_col, by{''.join(',' + c for c in extra)} FROM work_card_events "
                                  "WHERE item_id=? AND kind != 'state' ORDER BY at LIMIT ?", (item_id, MAX_ROWS)).fetchall()
            actors = []
            if _columns(conn, "work_write_actors"):
                actors = [dict(a) for a in conn.execute("SELECT op, actor_key, actor_session_id, cross_project, at FROM work_write_actors WHERE item_id=? "
                                                        "ORDER BY id LIMIT ?", (item_id, MAX_ROWS))]
        return {"item": dict(item), "messages": [dict(r) for r in msgs], "card_events": [dict(r) for r in events], "actors": actors}

    def task_manager_messages(self, item_ids: Iterable[int], start: float, end: float) -> List[Dict[str, Any]]:
        ids = list(item_ids)
        if not ids:
            return []
        with closing(self._huddle()) as conn:
            rows = conn.execute(f"SELECT id, item_id, author, author_key, kind, substr(text,1,400) AS text, created_at FROM work_messages "
                                f"WHERE item_id IN ({_marks(ids)}) AND created_at BETWEEN ? AND ? ORDER BY id LIMIT ?",
                                (*ids, start, end, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]

    def task_manager_items_by_creator(self, session_uuids: Sequence[str], start: float, end: float) -> List[Dict[str, Any]]:
        if not session_uuids:
            return []
        marks = _marks(session_uuids)
        with closing(self._huddle()) as conn:
            rows = conn.execute(f"SELECT id, list_key, text, created_by, state, created_at FROM work_items WHERE deleted=0 AND "
                                f"created_at BETWEEN ? AND ? AND (created_by IN ({marks}) OR id IN (SELECT item_id FROM work_card_events "
                                f"WHERE kind='created' AND by IN ({marks}))) ORDER BY id LIMIT ?",
                                (start, end, *session_uuids, *session_uuids, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]

    def sessions(self, refs: Sequence[str]) -> List[Dict[str, Any]]:
        if not refs:
            return []
        with closing(self._core()) as conn:
            cols = _columns(conn, "sessions")
            pick = [c for c in (*_SESSION_BASE, *_SESSION_OPTIONAL) if c in cols]
            ids = {r: r for r in refs}
            apps = [r for r in refs if r.startswith("ses_")]
            for app in apps:
                row = conn.execute("SELECT sender_uuid AS u FROM crosstalk_messages WHERE sender_id=? AND sender_uuid IS NOT NULL LIMIT 1", (app,)).fetchone() \
                    or conn.execute("SELECT receiver_uuid AS u FROM crosstalk_messages WHERE receiver_id=? AND receiver_uuid IS NOT NULL LIMIT 1", (app,)).fetchone()
                if row:
                    ids[app] = row["u"]
            wanted = list(dict.fromkeys(ids.values()))
            rows = conn.execute(f"SELECT {','.join(pick)} FROM sessions WHERE session_uuid IN ({_marks(wanted)}) "
                                f"OR claude_session_uuid IN ({_marks(wanted)}) OR tmux_name IN ({_marks(wanted)})",
                                (*wanted, *wanted, *wanted)).fetchall()
            out = [dict(r) for r in rows]
            for r in out:
                row = conn.execute("SELECT sender_id AS a FROM crosstalk_messages WHERE sender_uuid=? LIMIT 1", (r["session_uuid"],)).fetchone()
                r["app_id"] = row["a"] if row else None
        return out

    def conversations(self, session_uuids: Sequence[str]) -> List[Dict[str, Any]]:
        if not session_uuids:
            return []
        with closing(self._core()) as conn:
            rows = conn.execute(f"SELECT conversation_id, session_uuid, started_at, ended_at FROM conversation_index WHERE session_uuid IN "
                                f"({_marks(session_uuids)}) AND agent_family='claude' ORDER BY started_at", list(session_uuids)).fetchall()
            current = conn.execute(f"SELECT claude_session_uuid AS conversation_id, session_uuid, NULL AS started_at, NULL AS ended_at "
                                   f"FROM sessions WHERE session_uuid IN ({_marks(session_uuids)}) AND claude_session_uuid IS NOT NULL",
                                   list(session_uuids)).fetchall()
        seen: Dict[str, Dict[str, Any]] = {}
        for r in (*rows, *current):
            seen.setdefault(r["conversation_id"], dict(r))
        for conv in seen.values():
            conv["path"] = self._transcript_path(conv["conversation_id"])
        return list(seen.values())

    def _transcript_path(self, conversation_id: str) -> Optional[str]:
        from src.core.claude_config.transcript_roots import claude_transcript_roots  # noqa: PLC0415
        from src.core.transcript_manifest import lookup  # noqa: PLC0415

        found = lookup.transcript_path(conversation_id, "claude")
        if found is not None:
            return str(found)
        for root in claude_transcript_roots():
            try:
                hit = next(root.glob(f"*/{conversation_id}.jsonl"), None)
            except OSError:
                hit = None
            if hit is not None:
                return str(hit)
        return None

    def crosstalk(self, start: float, end: float, session_uuids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        with closing(self._core()) as conn:
            cols = _columns(conn, "crosstalk_messages")
            pick = [c for c in (*_CROSSTALK_BASE, *_CROSSTALK_OPTIONAL) if c in cols]
            sql = f"SELECT {','.join(pick)} FROM crosstalk_messages WHERE created_at BETWEEN ? AND ?"
            args: List[Any] = [start, end]
            if session_uuids:
                sql += f" AND (sender_uuid IN ({_marks(session_uuids)}) OR receiver_uuid IN ({_marks(session_uuids)}))"
                args += [*session_uuids, *session_uuids]
            rows = conn.execute(sql + " ORDER BY created_at LIMIT ?", (*args, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]

    def spawn_contacts(self, session_uuids: Sequence[str]) -> List[Dict[str, Any]]:
        if not session_uuids:
            return []
        with closing(self._core()) as conn:
            rows = conn.execute(f"SELECT left_key, right_key, granted_at FROM crosstalk_contacts WHERE source LIKE 'spawn%' AND "
                                f"(left_key IN ({_marks(session_uuids)}) OR right_key IN ({_marks(session_uuids)}))",
                                (*session_uuids, *session_uuids)).fetchall()
        return [dict(r) for r in rows]

    def lineage(self, node_ids: Sequence[str]) -> List[Dict[str, Any]]:
        if not node_ids:
            return []
        with closing(self._core()) as conn:
            rows = conn.execute(f"SELECT parent_type, parent_id, child_type, child_id, edge_kind, link_basis, created_at FROM lineage_edges "
                                f"WHERE edge_kind != 'subagent' AND (parent_id IN ({_marks(node_ids)}) OR child_id IN ({_marks(node_ids)})) LIMIT ?",
                                (*node_ids, *node_ids, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]

    def spawn_links(self, session_uuids: Sequence[str]) -> List[Dict[str, Any]]:
        if not session_uuids:
            return []
        with closing(self._core()) as conn:
            if not _columns(conn, "agent_spawn_links"):
                return []
            rows = conn.execute(f"SELECT child_id, child_uuid, parent_id, parent_uuid, parent_kind, task_message_id, spawned_at FROM "
                                f"agent_spawn_links WHERE child_uuid IN ({_marks(session_uuids)}) OR parent_uuid IN ({_marks(session_uuids)}) "
                                f"LIMIT ?", (*session_uuids, *session_uuids, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]

    def mcp_events(self, caller_ids: Sequence[str], start: float, end: float) -> List[Dict[str, Any]]:
        if not caller_ids:
            return []
        with closing(self._core()) as conn:
            if not _columns(conn, "mcp_events"):
                return []
            rows = conn.execute(f"SELECT call_id, started_at, tool, caller_session_id, target_ids, result_ids, outcome, duration_ms FROM mcp_events "
                                f"WHERE caller_session_id IN ({_marks(caller_ids)}) AND started_at BETWEEN ? AND ? ORDER BY started_at LIMIT ?",
                                (*caller_ids, start, end, MAX_ROWS)).fetchall()
        return [dict(r) for r in rows]
