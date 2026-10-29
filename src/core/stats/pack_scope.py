from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import structlog

from src.core.db import db_path_for
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.stats import project_groups
from src.core.stats.answers import digest
from src.core.stats.plugin.extract import project_key

logger = structlog.get_logger()

LOCAL = "local"
PACK_TABLES = ("minute_usage", "minute_counters")
_UNKNOWN = "unknown"
WARN_EVERY_SECONDS = 600.0

_PEER_USAGE = (
    f"(SELECT hour AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, input AS input_tokens, cache_write AS cache_write_tokens, "
    "cache_read AS cache_read_tokens, output AS output_tokens, "
    "CASE WHEN priced > 0 THEN cost_nano END AS estimated_cost_nano_usd, NULL AS price_version, messages AS usage_count, "
    "priced AS priced_usage_count, messages - priced AS unpriced_usage_count, 'ok' AS quality, "
    f"'{_UNKNOWN}' AS account_id, '{_UNKNOWN}' AS subagent_type FROM {USAGE_TABLE})")
_PEER_COUNTERS = (
    "(SELECT hour AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    f"COALESCE(agent_kind,'') AS agent_kind, counter, key, value FROM {COUNTER_TABLE})")
_LOCAL_LOSES = "(conversation_id || '|' || (minute_ts / 3600 * 3600)) IN (SELECT value FROM json_each(?))"
_PEER_LOSES = "(host || '|' || conversation_id || '|' || minute_ts) IN (SELECT value FROM json_each(?))"


@dataclass(frozen=True)
class Arm:

    source: Optional[str] = None
    skip: Optional[str] = None
    args: Tuple[Any, ...] = ()
    carnivore: Optional[Path] = None

    def where(self) -> Tuple[str, List[Any]]:
        return (f" AND NOT ({self.skip})", list(self.args)) if self.skip else ("", [])

    def connect(self, store: Any) -> Any:
        if self.carnivore is None:
            return store.connect(readonly=True)
        conn = sqlite3.connect(f"{self.carnivore.as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


@dataclass(frozen=True)
class Ownership:

    signature: str
    local_loses: FrozenSet[str] = frozenset()
    peer_loses: FrozenSet[str] = frozenset()
    has_peers: bool = False


@dataclass(frozen=True)
class PackQuery:

    arms: Tuple[Arm, ...]


_warn_lock = threading.Lock()
_warned_at = 0.0
_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[Tuple[int, str], Ownership]] = {}


def _warn_unreadable(error: Exception) -> None:
    """Say once per ``WARN_EVERY_SECONDS`` that the Pack tables could not be read. Input: the error."""
    global _warned_at
    with _warn_lock:
        if time.monotonic() - _warned_at < WARN_EVERY_SECONDS and _warned_at:
            return
        _warned_at = time.monotonic()
    logger.warning("stats_pack_scope_unreadable", error_type=type(error).__name__, detail=str(error)[:120])


def _app_path(store: Any) -> Path:
    return db_path_for(store.state_dir)


def _open_app(store: Any) -> Optional[sqlite3.Connection]:
    path = _app_path(store)
    if not path.exists():
        return None
    try:
        return Arm(carnivore=path).connect(store)
    except sqlite3.Error as exc:
        _warn_unreadable(exc)
        return None


def _rollup_state(app: sqlite3.Connection) -> List[Tuple[str, int, str]]:
    return [(r[0], int(r[1]), str(r[2])) for r in app.execute(
        f"SELECT peer_install_id, revision, scope_digest FROM {STATE_TABLE} ORDER BY peer_install_id")]


def _homes(app: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root, state, home, moved in app.execute(
            "SELECT root, pack_state, home_install_id, moved_to_install_id FROM projects WHERE pack_state != 'home'"):
        peer = moved if state == "moved_away" else home
        if root and peer:
            out[project_key(root)] = str(peer)
    return out


def _owners(store: Any, view: Any, app: sqlite3.Connection, signature: str) -> Ownership:
    db = view.connect(readonly=True)
    mine = {r[0] for r in db.execute("SELECT DISTINCT conversation_id FROM dim_source")}
    theirs = {r[0] for r in app.execute(
        f"SELECT conversation_id FROM {USAGE_TABLE} UNION SELECT conversation_id FROM {COUNTER_TABLE}")}
    overlap = sorted(mine & theirs)
    if not overlap:
        return Ownership(signature, has_peers=True)
    ids = json.dumps(overlap)
    local: Dict[Tuple[str, int], str] = {}
    for table in ("minute_usage", "minute_counters"):
        for conv, hour, project in db.execute(
                f"SELECT conversation_id, minute_ts / 3600 * 3600, project FROM {table} "
                "WHERE conversation_id IN (SELECT value FROM json_each(?)) GROUP BY 1, 2, 3 ORDER BY 3 DESC", (ids,)):
            local[(conv, hour)] = project
    peers: Dict[Tuple[str, int], Set[str]] = {}
    for table in (USAGE_TABLE, COUNTER_TABLE):
        for peer, conv, hour in app.execute(
                f"SELECT DISTINCT peer_install_id, conversation_id, hour FROM {table} "
                "WHERE conversation_id IN (SELECT value FROM json_each(?))", (ids,)):
            peers.setdefault((conv, hour), set()).add(peer)
    homes = _homes(app)
    groups = project_groups.groups_for(store) if homes else None
    local_loses: Set[str] = set()
    peer_loses: Set[str] = set()
    for key, holders in peers.items():
        here = key in local
        if not here and len(holders) == 1:
            continue
        home = homes.get(groups.group_of(local[key])) if (here and groups is not None) else None
        owner = home if home in holders else (LOCAL if here else min(holders))
        if here and owner != LOCAL:
            local_loses.add(f"{key[0]}|{key[1]}")
        peer_loses.update(f"{peer}|{key[0]}|{key[1]}" for peer in holders if peer != owner)
    return Ownership(signature, frozenset(local_loses), frozenset(peer_loses), has_peers=True)


def ownership(store: Any, view: Any) -> Optional[Ownership]:
    held = view.fingerprints.get("pack")
    if held is not None:
        return held or None
    app = _open_app(store)
    result: Optional[Ownership] = None
    if app is not None:
        with closing(app):
            try:
                states = _rollup_state(app)
                if states:
                    signature = digest(states, sorted(_homes(app).items()))
                    key = (view.revision(), signature)
                    with _cache_lock:
                        hit = _cache.get(str(store.state_dir))
                    if hit is not None and hit[0] == key:
                        result = hit[1]
                    else:
                        result = _owners(store, view, app, signature)
                        with _cache_lock:
                            _cache[str(store.state_dir)] = (key, result)
            except sqlite3.Error as exc:
                _warn_unreadable(exc)
    view.fingerprints["pack"] = result or False
    return result


def signature(store: Any, view: Any) -> str:
    found = ownership(store, view)
    return found.signature if found is not None else "no-pack"


def for_request(store: Any, view: Any, request: Any, table: str) -> Optional[PackQuery]:
    if getattr(request, "scope", "local") != "pack" or table not in PACK_TABLES:
        return None
    owned = ownership(store, view)
    if owned is None:
        return None
    host = request.filters.host
    arms: List[Arm] = []
    if host in (None, LOCAL):
        arms.append(Arm(skip=_LOCAL_LOSES, args=(json.dumps(sorted(owned.local_loses)),)) if owned.local_loses else Arm())
    if host != LOCAL:
        source = _PEER_USAGE if table == "minute_usage" else _PEER_COUNTERS
        arms.append(Arm(source, _PEER_LOSES, (json.dumps(sorted(owned.peer_loses)),), _app_path(store))
                    if owned.peer_loses else Arm(source, carnivore=_app_path(store)))
    return PackQuery(tuple(arms))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def roster_view() -> Tuple[str, Dict[str, bool]]:
    from src.core.pack.machines import roster as roster_mod, runtime

    wired = runtime.wiring()
    if wired is None:
        return "this computer", {}
    online = {}
    for peer in wired.peers():
        state = wired.runtime.roster.peer_state(peer)
        online[peer.install_id] = state in (roster_mod.STATE_CONNECTED, roster_mod.STATE_WAITING, roster_mod.STATE_OLDER)
    return wired.runtime.label or "this computer", online


def computers(store: Any, self_label: str, online: Dict[str, bool]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [{"id": LOCAL, "label": self_label, "self": True, "online": True, "through": None}]
    app = _open_app(store)
    if app is None:
        return out
    with closing(app):
        try:
            labels = {r[0]: r[1] for r in app.execute(
                "SELECT peer_install_id, label FROM hosts WHERE peer_install_id IS NOT NULL AND peer_install_id != ''")}
            for peer, pulled in app.execute(f"SELECT peer_install_id, pulled_at FROM {STATE_TABLE} ORDER BY peer_install_id"):
                newest = app.execute(f"SELECT MAX(hour) FROM {USAGE_TABLE} WHERE peer_install_id = ?", (peer,)).fetchone()[0]
                up = online.get(peer, True)
                through = None
                if not up and newest is not None:
                    through = _iso(min(newest + 3600, pulled) if pulled else newest + 3600)
                out.append({"id": peer, "label": labels.get(peer) or peer[:8], "self": False, "online": up, "through": through})
        except sqlite3.Error as exc:
            _warn_unreadable(exc)
    return out


def host_dimension(store: Any, self_label: str, online: Dict[str, bool]) -> Dict[str, Any]:
    items = [{"key": c["id"], "label": c["label"], "filter_value": c["id"], "minute_rows": 0} for c in computers(
        store, self_label, online)]
    return {"items": items, "next_cursor": None, "total": len(items)}


def annotate(store: Any, results: List[Dict[str, Any]], online: Dict[str, bool], self_label: str) -> List[Dict[str, Any]]:
    if not any(r.get("ok") and r["result"].get("scope") == "pack" for r in results):
        return results
    offline = [{"id": c["id"], "label": c["label"], "through": c["through"]}
               for c in computers(store, self_label, online) if not c["online"] and c["through"]]
    return [({**r, "result": {**r["result"], "pack": {"offline": offline}}}
             if r.get("ok") and r["result"].get("scope") == "pack" else r) for r in results]
