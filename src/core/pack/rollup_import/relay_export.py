
from __future__ import annotations

import base64
import json
import sqlite3
import threading
from contextlib import closing
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.computers import direction
from src.core.db import transaction
from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope
from src.core.pack.rollup_import import relay_store, signed, v2_export, v2_store
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, PROJECTS_TABLE, REV_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.pack.rollup_import.relay_store import MAX_HOPS
from src.core.deepsearch import peer_air_gap
from src.core.stats import pack_scope, project_groups, rollup
from src.core.stats.plugin import revision


class RelayExportError(ValueError):
    pass


logger = structlog.get_logger()

STREAMS = ("own", "relay")
MAX_ORIGINS = 64
MAX_HEADER_BYTES = 400 * 1024
MAX_V2_HEADER_BYTES = 768 * 1024
_CHUNK = 200
_ENVELOPE_BYTES = 2048
_noted: set = set()

_NEXT_SQL = (
    f"SELECT peer_install_id, conversation_id, hour, rev, origin_rev, epoch, sig FROM {REV_TABLE} WHERE rev > ? AND rev <= ? "
    "AND (rev, hour, conversation_id, peer_install_id) > (?, ?, ?, ?) "
    "AND peer_install_id IN (SELECT value FROM json_each(?)) AND (? = 0 OR (sig IS NOT NULL AND origin_rev IS NOT NULL AND epoch IS NOT NULL)) "
    "ORDER BY rev, hour, conversation_id, peer_install_id LIMIT ?")
_USAGE_SQL = (
    "SELECT model, project, input, cache_write, cache_read, output, cost_nano, messages, priced, provider, agent_kind, agent_name "
    f"FROM {USAGE_TABLE} WHERE peer_install_id = ? AND conversation_id = ? AND hour = ? ORDER BY model, project")
_COUNTER_SQL = (
    f"SELECT model, project, counter, key, value, provider, agent_kind FROM {COUNTER_TABLE} "
    "WHERE peer_install_id = ? AND conversation_id = ? AND hour = ? ORDER BY model, project, counter, key")


def encode_relay_cursor(rev: int, hour: int, conversation_id: str, origin: str) -> str:
    raw = json.dumps([rev, hour, conversation_id, origin], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_relay_cursor(cursor: Optional[str]) -> Tuple[int, int, str, str]:
    if not cursor:
        return (-1, -1, "", "")
    try:
        rev, hour, conversation_id, origin = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError) as exc:
        raise RelayExportError("bad relay cursor") from exc
    if not (isinstance(rev, int) and isinstance(hour, int) and isinstance(conversation_id, str) and isinstance(origin, str)):
        raise RelayExportError("bad relay cursor")
    return (rev, hour, conversation_id, origin)


def advertised(open_db: Callable[[], sqlite3.Connection]) -> Dict[str, int]:
    try:
        with closing(open_db()) as conn:
            value = relay_store.current_rev(conn)
    except sqlite3.Error as exc:
        logger.info("pack_rollup_relay_revision_unreadable", error_type=type(exc).__name__)
        return {}
    return {} if value is None else {"relay": value}


def _origins(conn: sqlite3.Connection, caller: str, withheld: FrozenSet[str] = frozenset()) -> Dict[str, Dict[str, Any]]:
    found: List[Tuple[int, str, Dict[str, Any]]] = []
    for iid, via, hops, label, one_way, digest, rev, pulled in conn.execute(
            f"SELECT peer_install_id, via, hops, label, one_way, scope_digest, revision, origin_pulled_at FROM {STATE_TABLE}"):
        ways = relay_store.id_list(one_way)
        if iid == caller or via == caller or caller in ways or iid in withheld or hops + 1 > MAX_HOPS:
            continue
        peer = peer_hosts.get(conn, iid)
        found.append((hops, iid, {"hops": hops, "label": (peer.label if peer is not None else None) or label or "", "revision": int(rev),
                                  "scope_digest": digest, "pulled_at": pulled, "one_way": ways}))
    found.sort(key=lambda item: (item[0], item[1]))
    return {iid: entry for _hops, iid, entry in found[:MAX_ORIGINS]}


def _names(conn: sqlite3.Connection, origins: List[str], deny: FrozenSet[str]) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    names: Dict[str, Dict[str, str]] = {}
    homes: Dict[str, Dict[str, str]] = {}
    for origin, project, name, home in conn.execute(
            f"SELECT peer_install_id, project, name, home_install_id FROM {PROJECTS_TABLE} "
            "WHERE peer_install_id IN (SELECT value FROM json_each(?))", (json.dumps(origins),)):
        if project in deny:
            continue
        names.setdefault(origin, {})[project] = name
        if home:
            homes.setdefault(origin, {})[project] = home
    return names, homes


def _signed_names(conn: sqlite3.Connection, origins: List[str], deny: FrozenSet[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for origin in origins:
        proof = relay_store.names_proof(conn, origin)
        if proof is None:
            continue
        names, homes = _names(conn, [origin], frozenset())
        held = names.get(origin, {})
        if any(key in deny for key in held):
            if "names_denied" not in _noted:
                _noted.add("names_denied")
                logger.warning("pack_rollup_relay_signed_names_left_out")
            continue
        out[origin] = {"names": held, "homes": homes.get(origin, {}), "names_rev": proof[0], "names_epoch": proof[2], "names_sig": {"signer": origin, "sig": proof[1]}}
    return out


def _group(conn: sqlite3.Connection, origin: str, conversation_id: str, hour: int, rev: int, deny: FrozenSet[str],
           proof: Optional[Tuple[Optional[int], Optional[int], Optional[str]]] = None) -> Optional[Dict[str, Any]]:
    stored_usage = conn.execute(_USAGE_SQL, (origin, conversation_id, hour)).fetchall()
    stored_counters = conn.execute(_COUNTER_SQL, (origin, conversation_id, hour)).fetchall()
    usage = [r for r in stored_usage if r[1] not in deny]
    counters = [r for r in stored_counters if r[1] not in deny]
    if (stored_usage or stored_counters) and not (usage or counters):
        return None
    if proof is not None and (len(usage) != len(stored_usage) or len(counters) != len(stored_counters)):
        return None
    first = (usage[0][9], usage[0][10], usage[0][11]) if usage else ((counters[0][5], counters[0][6], None) if counters else (None, None, None))
    group: Dict[str, Any] = {
        "origin": origin, "conversation_id": conversation_id, "provider": first[0], "agent_kind": first[1], "hour": hour, "rev": rev,
        "usage": [list(r[:9]) for r in usage], "counters": [list(r[:5]) for r in counters]}
    if first[2]:
        group["agent_name"] = first[2]
    if proof is not None:
        group["orev"], group["epoch"], group["sig"] = proof[0], proof[1], {"signer": origin, "sig": proof[2]}
    return group


def _relay_page(store: Any, open_app: Callable[[], sqlite3.Connection], caller: str, since_revision: int, until_revision: Optional[int],
                cursor: Optional[str], max_bytes: int, signed_form: bool = False, withheld: FrozenSet[str] = frozenset(),
                include_v2: bool = False) -> Dict[str, Any]:
    from src.core.stats import config

    if not config.get_settings(store)["enabled"]:
        return {"available": False, "reason": "stats_off"}
    try:
        deny = rollup.withheld_keys(store)
    except peer_air_gap.AirGapUnreadable:
        logger.warning("stats_rollup_air_gap_unreadable")
        return {"available": False, "reason": "projects_unreadable"}
    after = decode_relay_cursor(cursor)
    with closing(open_app()) as conn:
        current = relay_store.current_rev(conn) or 0
        reset = since_revision > current or since_revision < 0
        since = 0 if reset else since_revision
        until = current if until_revision is None else max(0, min(until_revision, current))
        origins = _origins(conn, caller, withheld)
        if cursor is None:
            if signed_form:
                signed_names = _signed_names(conn, list(origins), deny)
                with_names = {iid: {**entry, **signed_names.get(iid, {})} for iid, entry in origins.items()}
            else:
                names, homes = _names(conn, list(origins), deny)
                with_names = {iid: {**entry, "names": names.get(iid, {}), "homes": homes.get(iid, {})} for iid, entry in origins.items()}
            if len(json.dumps(with_names, separators=(",", ":"))) <= MAX_HEADER_BYTES:
                origins = with_names
            elif "names" not in _noted:
                _noted.add("names")
                logger.warning("pack_rollup_relay_names_left_out", origins=len(origins))
            if include_v2:
                running = len(json.dumps(origins, separators=(",", ":")))
                for iid in list(origins):
                    extra = v2_store.relay_v2_for(conn, iid, deny, signed_form)
                    if extra is None:
                        continue
                    extra_size = len(json.dumps(extra, separators=(",", ":")))
                    if running + extra_size <= MAX_V2_HEADER_BYTES:
                        origins[iid] = {**origins[iid], **extra}
                        running += extra_size
                    elif "v2_budget" not in _noted:
                        _noted.add("v2_budget")
                        logger.warning("pack_rollup_relay_v2_budget_exceeded", origin=iid[:8])
        header = len(json.dumps(origins, separators=(",", ":")))
        budget = max(4096, min(int(max_bytes), rollup.MAX_PAGE_BYTES)) - _ENVELOPE_BYTES - header
        ids = json.dumps(sorted(origins))
        groups: List[Dict[str, Any]] = []
        used, last, complete, more = 0, after, True, bool(origins)
        while more and complete:
            chunk = conn.execute(_NEXT_SQL, (since, until, *last, ids, 1 if signed_form else 0, _CHUNK)).fetchall()
            for origin, conversation_id, hour, rev, origin_rev, epoch, sig in chunk:
                group = _group(conn, origin, conversation_id, hour, rev, deny, (origin_rev, epoch, sig) if signed_form else None)
                size = len(json.dumps(group, separators=(",", ":"))) if group is not None else 0
                if groups and used + size > budget:
                    complete = False
                    break
                last = (rev, hour, conversation_id, origin)
                if group is not None:
                    groups.append(group)
                    used += size
            more = len(chunk) == _CHUNK
    return {
        "available": True, "stream": "relay", "revision": current, "since_revision": since, "until_revision": until, "reset": reset,
        "complete": complete, "next_cursor": None if complete else encode_relay_cursor(*last),
        "scope_digest": rollup.scope_digest(deny), "usage_columns": list(rollup.USAGE_COLUMNS),
        "counter_columns": list(rollup.COUNTER_COLUMNS), "origins": origins, "groups": groups}


def _own_v2(store: Any, open_app: Callable[[], sqlite3.Connection]) -> Optional[Dict[str, Any]]:
    try:
        allow = rollup.allowed_projects(store)
        with store.connect() as conn:
            revoked = revision.settle(conn, allow)
    except (peer_air_gap.AirGapUnreadable, sqlite3.Error) as exc:
        logger.info("pack_rollup_v2_unreadable", error_type=type(exc).__name__)
        return None
    return v2_export.build_v2(store, open_app, allow_projects=allow, revoked_projects=revoked)


def _own_extras(store: Any, open_app: Callable[[], sqlite3.Connection]) -> Dict[str, Any]:
    try:
        allow = rollup.allowed_projects(store)
        with store.connect() as conn:
            revoked = revision.settle(conn, allow)
            keys = [r[0] for r in conn.execute("SELECT name FROM dim_project")] if revision.exists(conn) else []
        with closing(open_app()) as app:
            homes = pack_scope.project_homes(app)
    except (peer_air_gap.AirGapUnreadable, sqlite3.Error) as exc:
        logger.info("pack_rollup_names_unreadable", error_type=type(exc).__name__)
        return {"project_names": {}, "project_homes": {}}
    groups = project_groups.groups_for(store)
    names: Dict[str, str] = {}
    hints: Dict[str, str] = {}
    for key in sorted(keys):
        if len(names) >= relay_store.MAX_NAMES:
            break
        if (allow is not None and key not in allow) or key in revoked:
            continue
        group = groups.group_of(key)
        if group in groups.labels:
            names[key] = groups.labels[group]
            if group in homes:
                hints[key] = homes[group]
    return {"project_names": names, "project_homes": hints}


_SIGNED_OWN_LOCK = threading.Lock()


def _signed_own(page: Dict[str, Any], store: Any, open_app: Callable[[], sqlite3.Connection], signing: Signing, first_page: bool,
                include_v2: bool = False) -> Dict[str, Any]:
    key_id = envelope.own_kid(signing)
    if key_id is None:
        return {"available": False, "reason": "key_unavailable"}
    with closing(open_app()) as conn, transaction(conn):
        epoch = relay_store.scope_epoch(conn, page["scope_digest"])
    out = {**page, "scope_digest": f"{page['scope_digest']}.{key_id}", "groups": signed.sign_own_groups(page["groups"], signing, epoch)}
    if first_page:
        extras = _own_extras(store, open_app)
        proof = signed.sign_names(extras["project_names"], extras["project_homes"], page["until_revision"], signing, epoch)
        if proof is not None:
            out.update(proof)
        if include_v2:
            v2_payload = _own_v2(store, open_app)
            if v2_payload is not None:
                stamp = max(int(page["until_revision"]), v2_export.stats_revision(store))
                v2_signed = v2_export.sign_v2(v2_payload, stamp, signing, epoch)
                if v2_signed is not None:
                    out.update(v2_signed)
    return out


def serve_stream(store: Any, open_app: Callable[[], sqlite3.Connection], *, caller: str, stream: Optional[str], since_revision: int = 0,
                 until_revision: Optional[int] = None, cursor: Optional[str] = None, max_bytes: int = rollup.PAGE_BYTES,
                 signing: Optional[Signing] = None, withheld: FrozenSet[str] = frozenset(), include_v2: bool = False) -> Dict[str, Any]:
    signed_form = signing is not None and capabilities.mesh_on()
    if stream is None:
        page = rollup.serve(store, since_revision=since_revision, until_revision=until_revision, cursor=cursor, max_bytes=max_bytes)
        if include_v2 and cursor is None and page.get("available") is True:
            v2_payload = _own_v2(store, open_app)
            if v2_payload is not None:
                page = {**page, "v2": v2_payload}
        return page
    if stream == "relay":
        return _relay_page(store, open_app, caller, since_revision, until_revision, cursor, max_bytes, signed_form, withheld, include_v2=include_v2)
    if stream != "own":
        raise RelayExportError("unknown rollup stream")
    if signed_form:
        with _SIGNED_OWN_LOCK:
            page = rollup.serve(store, since_revision=since_revision, until_revision=until_revision, cursor=cursor, max_bytes=max_bytes)
            if page.get("available") is not True:
                return page
            return _signed_own({**page, "stream": "own", "one_way": direction.one_way_ids()}, store, open_app, signing, cursor is None, include_v2=include_v2)
    page = rollup.serve(store, since_revision=since_revision, until_revision=until_revision, cursor=cursor, max_bytes=max_bytes)
    if page.get("available") is not True:
        return page
    page = {**page, "stream": "own", "one_way": direction.one_way_ids()}
    if cursor is None:
        page = {**page, **_own_extras(store, open_app)}
        if include_v2:
            v2_payload = _own_v2(store, open_app)
            if v2_payload is not None:
                page["v2"] = v2_payload
    return page
