
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.inventory import registry
from src.core.inventory.claim_rows import annotate, open_side, trace_claims
from src.core.inventory.model import (DELETE, KEEP, KIND_ENTRY, KIND_ROWS, REPORT, ROLE_KEY, Artifact, FieldRef,
                                      SessionIdentity)
from src.core.inventory.registry_side import ATTENTION as ATTENTION_HISTORY_DB
from src.core.inventory.registry_side import BOOKMARKS as BOOKMARKS_DB
from src.core.inventory.registry_side import SIDE_DBS, side_db_path
from src.core.inventory.scope import Scope

logger = structlog.get_logger()

PREFERENCES = "ui_preferences"
JOURNAL = "session-journal"


def _sqlite_rows(path: Path, table: str, where: str, params: List[Any], store: str, action: str = DELETE,
                 reason: str = "") -> Optional[Artifact]:
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return None
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
    except sqlite3.Error as exc:
        logger.warning("session_purge_side_db_unreadable", store=store, error=str(exc))
        return Artifact(store=store, kind=KIND_ROWS, what=table, count=0, action=REPORT,
                        reason=f"could not be read ({type(exc).__name__}); nothing there is removed")
    if not count:
        return None
    return Artifact(store=store, kind=KIND_ROWS, what=table, count=count, action=action, reason=reason,
                    locator={"table": table, "where": where, "params": list(params), "db": str(path)})


def _side_dbs(state_dir: Path, ident: SessionIdentity, conv_owned: bool, shared_reason: str) -> List[Artifact]:
    out: List[Optional[Artifact]] = [
        _sqlite_rows(state_dir / BOOKMARKS_DB, "bookmarks", "session_uuid = ? OR session_row_id = ?",
                     [ident.session_uuid, ident.row_id], BOOKMARKS_DB),
        _sqlite_rows(state_dir / ATTENTION_HISTORY_DB, "attention_events", "session_uuid = ?", [ident.session_uuid],
                     ATTENTION_HISTORY_DB),
    ]
    if ident.conversation:
        out.append(_sqlite_rows(
            state_dir / BOOKMARKS_DB, "bookmarks",
            "claude_session_uuid = ? AND session_uuid != ? AND COALESCE(session_row_id, -1) != ?",
            [ident.conversation, ident.session_uuid, ident.row_id], BOOKMARKS_DB,
            action=DELETE if conv_owned else KEEP, reason=shared_reason))
    return [a for a in out if a is not None]


def _search_cache(state_dir: Path, ident: SessionIdentity, action: str, reason: str) -> Optional[Artifact]:
    from src.core.deepsearch import constants as K
    from src.core.deepsearch.cache import db as cache_db

    if not ident.conversation or not cache_db.cache_path(state_dir).exists():
        return None
    try:
        with closing(cache_db.open_cache(state_dir)) as conn:
            count = int(conn.execute(f"SELECT COUNT(*) FROM {K.LIVE_TABLE} WHERE conversation_id = ?",
                                     (ident.conversation,)).fetchone()[0])
    except sqlite3.Error as exc:
        logger.warning("session_purge_side_db_unreadable", store=K.CACHE_FILENAME, error=str(exc))
        return None
    if not count:
        return None
    return Artifact(store=K.CACHE_FILENAME, kind=KIND_ROWS, what=f"{K.LIVE_TABLE} (with its rows and postings)",
                    count=count, action=action, reason=reason,
                    locator={"table": K.LIVE_TABLE, "where": "conversation_id = ?", "params": [ident.conversation],
                             "db": str(cache_db.cache_path(state_dir))},
                    op={"fn": "search_cache", "state_dir": str(state_dir), "conversation": ident.conversation})


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("session_purge_json_unreadable", path=str(path), error=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


def prune_preferences(values: Dict[str, Any], ident: SessionIdentity) -> Tuple[Dict[str, Any], int, int]:
    changes: Dict[str, Any] = {}
    uuid = ident.session_uuid
    removed = 0
    arrangement = values.get("drawer_arrangement")
    if isinstance(arrangement, dict):
        fresh = dict(arrangement)
        for key in ("pinned", "order"):
            items = arrangement.get(key)
            if isinstance(items, list) and uuid in items:
                removed += items.count(uuid)
                fresh[key] = [i for i in items if i != uuid]
        bands = arrangement.get("bands")
        if isinstance(bands, dict):
            new_bands = {}
            for band, items in bands.items():
                if isinstance(items, list) and uuid in items:
                    removed += items.count(uuid)
                    items = [i for i in items if i != uuid]
                new_bands[band] = items
            fresh["bands"] = new_bands
        if removed:
            changes["drawer_arrangement"] = fresh
    layouts_removed = 0
    layouts = values.get("terminal_layouts")
    key = ident.layout_key
    if isinstance(layouts, dict) and key and isinstance(layouts.get("sessions"), dict) and key in layouts["sessions"]:
        sessions = {k: v for k, v in layouts["sessions"].items() if k != key}
        changes["terminal_layouts"] = {**layouts, "sessions": sessions}
        layouts_removed = 1
    return changes, removed, layouts_removed


def _foreign_tabs(values: Dict[str, Any], ident: SessionIdentity) -> int:
    layouts = values.get("terminal_layouts")
    sessions = layouts.get("sessions") if isinstance(layouts, dict) else None
    if not isinstance(sessions, dict):
        return 0
    needle = f'"terminal:row:{ident.row_id}"'
    return sum(1 for k, v in sessions.items() if k != ident.layout_key and needle in json.dumps(v))


def _preferences(config_path: Path, ident: SessionIdentity) -> List[Artifact]:
    from src.core import ui_preferences

    config = _read_json(config_path)
    if config is None:
        return []
    values = ui_preferences.read_block(config).get("values") or {}
    _changes, arranged, layouts = prune_preferences(values, ident)
    out: List[Artifact] = []
    if arranged:
        out.append(Artifact(store=PREFERENCES, kind=KIND_ENTRY, what="drawer_arrangement", count=arranged,
                            locator={"file": str(config_path), "key": "ui_preferences.values.drawer_arrangement"},
                            rewrite=[FieldRef("pinned / order / bands[*]: session_uuid", ROLE_KEY)],
                            op={"fn": "preferences", "field": "drawer_arrangement", "config": str(config_path)}))
    if layouts:
        out.append(Artifact(store=PREFERENCES, kind=KIND_ENTRY, what=f"terminal_layouts[{ident.layout_key}]",
                            count=layouts, locator={"file": str(config_path),
                                                    "key": f"ui_preferences.values.terminal_layouts.sessions.{ident.layout_key}"},
                            rewrite=[FieldRef("sessions key: <tmux name>:<epoch>", ROLE_KEY),
                                     FieldRef("terminal:row:<sessions.id> tab keys", ROLE_KEY)],
                            op={"fn": "preferences", "field": "terminal_layouts", "config": str(config_path)}))
    foreign = _foreign_tabs(values, ident)
    if foreign:
        out.append(Artifact(store=PREFERENCES, kind=KIND_ENTRY, what=f"terminal:row:{ident.row_id} tabs", count=foreign,
                            action=REPORT, reason="a tab inside another session's grid; that grid drops a tab whose "
                            "row is gone, and its arrangement is that session's to rewrite",
                            locator={"file": str(config_path), "key": "ui_preferences.values.terminal_layouts.sessions"},
                            rewrite=[FieldRef("terminal:row:<sessions.id> tab keys", ROLE_KEY)]))
    return out


def _journal_matches(entry: Any, ident: SessionIdentity) -> bool:
    return isinstance(entry, dict) and (entry.get("session_uuid") == ident.session_uuid
                                        or entry.get("row_id") == ident.row_id)


def _journal(state_dir: Path, ident: SessionIdentity) -> Tuple[List[Artifact], List[str]]:
    from src.core import session_journal_store as store

    loaded = store.load_journal(state_dir)
    if loaded.outcome == store.LOAD_ABSENT:
        return [], []
    if loaded.outcome != store.LOAD_OK:
        return [], [f"the reboot journal is unreadable ({loaded.detail}); it cannot be cleaned safely"]
    journal = loaded.journal
    blockers: List[str] = []
    if journal.get("offer") and ident.session_uuid in json.dumps(journal["offer"]):
        blockers.append("the open reopen offer names this session; answer the offer first")
    count = sum(1 for part in ("sessions", "declined") if isinstance(journal.get(part), dict)
                for entry in journal[part].values() if _journal_matches(entry, ident))
    if not count:
        return [], blockers
    return [Artifact(store=JOURNAL, kind=KIND_ENTRY, what=str(store.journal_path(state_dir)), count=count,
                     locator={"file": str(store.journal_path(state_dir)), "key": "sessions / declined"},
                     rewrite=[FieldRef("session_uuid", ROLE_KEY), FieldRef("row_id", ROLE_KEY)],
                     op={"fn": "journal", "state_dir": str(state_dir)})], blockers


def _pinned_theme(pins_path: Optional[Path], ident: SessionIdentity) -> List[Artifact]:
    if pins_path is None or not ident.tmux_name:
        return []
    data = _read_json(pins_path)
    if not data or ident.tmux_name not in data:
        return []
    return [Artifact(store="pinned_themes.json", kind=KIND_ENTRY, what=ident.tmux_name, count=1, action=REPORT,
                     reason="keyed by tmux name, which a later session may reuse, and held in memory by the server; "
                     "the server's own ownership pass prunes it",
                     locator={"file": str(pins_path), "key": ident.tmux_name}, rewrite=[FieldRef("tmux name", ROLE_KEY)])]


def claimed_side_rows(state_dir: Path, scope: Scope) -> List[Artifact]:
    book = registry.book()
    out: List[Artifact] = []
    for store in SIDE_DBS:
        path = side_db_path(state_dir, store)
        try:
            with open_side(path) as conn:
                if conn is not None:
                    out += trace_claims(book, scope, store, conn, path)
        except sqlite3.Error as exc:
            logger.warning("inventory_side_db_unreadable", store=store, error=str(exc))
            out.append(Artifact(store=store, kind=KIND_ROWS, what="(whole file)", count=0, action=REPORT,
                                reason=f"could not be opened ({type(exc).__name__}); nothing there is counted"))
    return out


def trace(state_dir: Path, config_path: Path, ident: SessionIdentity, shared_reason: str,
          pins_path: Optional[Path] = None, scope: Optional[Scope] = None) -> Tuple[List[Artifact], List[str]]:
    arts = _side_dbs(state_dir, ident, not shared_reason, shared_reason)
    cache_art = _search_cache(state_dir, ident, DELETE if not shared_reason else KEEP, shared_reason)
    arts += [cache_art] if cache_art else []
    arts += _preferences(config_path, ident)
    journal_arts, blockers = _journal(state_dir, ident)
    arts += journal_arts
    arts += _pinned_theme(pins_path, ident)
    if scope is not None:
        annotate(registry.book(), arts, scope)
        arts += claimed_side_rows(state_dir, scope)
    return arts, blockers


def _delete_sqlite(art: Artifact) -> int:
    loc = art.locator
    with closing(sqlite3.connect(loc["db"], timeout=30.0)) as conn:
        with conn:
            return conn.execute(f"DELETE FROM {loc['table']} WHERE {loc['where']}", loc["params"]).rowcount


def _delete_search_cache(art: Artifact, ident: SessionIdentity) -> int:
    from src.core.db import transaction
    from src.core.deepsearch.cache import db as cache_db
    from src.core.deepsearch.live import store

    with closing(cache_db.open_cache(Path(art.op["state_dir"]))) as conn:
        with transaction(conn):
            files = store.of_conversation(conn, art.op["conversation"])
            for live in files:
                store.delete_file(conn, int(live.id))
    return len(files)


def _delete_preferences(art: Artifact, ident: SessionIdentity) -> int:
    from src.core import config_writer, ui_preferences

    removed = {"n": 0}

    def mutate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        values = ui_preferences.read_block(doc).get("values") or {}
        changes, arranged, layouts = prune_preferences(values, ident)
        name = art.op["field"]
        if name not in changes:
            return None
        removed["n"] = arranged if name == "drawer_arrangement" else layouts
        new_doc, _block, _moved = ui_preferences.apply_changes(doc, {name: changes[name]})
        return new_doc

    config_writer.commit(Path(art.op["config"]), mutate)
    return removed["n"]


def _delete_journal(art: Artifact, ident: SessionIdentity) -> int:
    from src.core import session_journal_store as store

    state_dir = Path(art.op["state_dir"])
    loaded = store.load_journal(state_dir)
    if loaded.outcome != store.LOAD_OK:
        raise OSError(f"the reboot journal could not be read: {loaded.detail}")
    journal = dict(loaded.journal)
    removed = 0
    for part in ("sessions", "declined"):
        entries = journal.get(part)
        if isinstance(entries, dict):
            kept = {k: v for k, v in entries.items() if not _journal_matches(v, ident)}
            removed += len(entries) - len(kept)
            journal[part] = kept
    if removed and not store.save_journal(state_dir, journal):
        raise OSError("the reboot journal could not be written")
    return removed


_DELETES: Dict[str, Callable[[Artifact, SessionIdentity], int]] = {
    "preferences": _delete_preferences, "journal": _delete_journal, "search_cache": _delete_search_cache,
}


def delete(art: Artifact, ident: SessionIdentity) -> int:
    if "fn" not in art.op:
        return _delete_sqlite(art)
    return _DELETES[art.op["fn"]](art, ident)
