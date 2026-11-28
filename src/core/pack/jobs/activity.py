
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.pack.jobs import load_report
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobState, TERMINAL
from src.core.pack.jobs.view import WARM_PREFIX, _listing_uuid

log = structlog.get_logger(__name__)

CAP_ACTIVITY = "pack.jobs.activity"
PEER_ACTIVITY_TIMEOUT_S = 2.5
DAY = 86400.0
_HOST_LIVE = frozenset({"preparing", "running", "parked"})
_CALLER_DONE = frozenset(s.value for s in TERMINAL)


def _trim(text: Optional[str], limit: int = 180) -> str:
    if not text:
        return ""
    line = str(text).strip().splitlines()[0].strip() if str(text).strip() else ""
    return (line[: max(1, limit - 3)] + "...") if len(line) > limit else line


def _parse_ts(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        iso = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _session_label(row: Dict[str, Any]) -> str:
    for key in ("title", "claude_title", "short_description", "tmux_name"):
        val = str(row.get(key) or "").strip()
        if val:
            return _trim(val, 120)
    agent = str(row.get("agent_type") or row.get("agent_family") or "agent").strip()
    uid = str(row.get("session_uuid") or "")[:8]
    return f"{agent} {uid}".strip()


def _job_tone(state: str, live: bool) -> str:
    if state in ("done", "exited"):
        return "ok"
    if state in ("failed", "lost", "refused", "missing"):
        return "danger"
    if state in ("question", "parked", "waiting_approval"):
        return "warn"
    if state in ("stopped", "here"):
        return "neutral"
    if state in ("running", "preparing", "starting", "sent"):
        return "ok"
    return "info" if live else "neutral"


def _session_status(lifecycle: str, activity: str, archived: Any) -> Tuple[bool, str, str]:
    lc = (lifecycle or "").lower()
    act = (activity or "").lower()
    if lc == "running":
        if act in ("waiting", "needs_input", "asking", "permission", "question", "notice"):
            return True, "waiting", "warn"
        if act in ("working", "working_subagent", "running", "active", "busy"):
            return True, "working", "ok"
        return True, "idle", "neutral"
    if archived:
        return False, "archived", "neutral"
    if lc in ("asleep", "sleeping"):
        return False, "sleeping", "neutral"
    return False, "closed", "neutral"


def _open_carnivore_db(state_dir: Path) -> Optional[sqlite3.Connection]:
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    path = db_path_for(state_dir)
    if not path.exists():
        return None
    try:
        conn = connect(path, create=False)
        conn.row_factory = sqlite3.Row
        return conn
    except (OSError, sqlite3.Error, DatastoreUnreadableError):
        return None


def _self_identity(state_dir: Path) -> Tuple[str, str]:
    try:
        from src.core.pack.machines import runtime as machines_runtime

        wired = machines_runtime.wiring()
        if wired is not None:
            return str(wired.runtime.install_id or "local"), str(wired.runtime.label or "this computer")
    except Exception:  # noqa: BLE001
        pass
    conn = _open_carnivore_db(state_dir)
    if conn is not None:
        with closing(conn):
            try:
                row = conn.execute("SELECT install_id, label FROM pack_machines WHERE is_self=1 LIMIT 1").fetchone()
                if row:
                    return str(row["install_id"] or "local"), str(row["label"] or "this computer")
            except sqlite3.Error:
                pass
    return "local", "this computer"


def _session_title_map(conn: Optional[sqlite3.Connection]) -> Tuple[Dict[str, str], Dict[int, Tuple[str, str]]]:
    by_uuid: Dict[str, str] = {}
    by_id: Dict[int, Tuple[str, str]] = {}
    if conn is None:
        return by_uuid, by_id
    try:
        rows = conn.execute(
            "SELECT id, session_uuid, title, claude_title, short_description, tmux_name, agent_type, agent_family "
            "FROM sessions"
        ).fetchall()
    except sqlite3.Error:
        return by_uuid, by_id
    for r in rows:
        d = dict(r)
        lbl = _session_label(d)
        uid = str(d.get("session_uuid") or "")
        if uid:
            by_uuid[uid] = lbl
        if d.get("id") is not None:
            by_id[int(d["id"])] = (uid, lbl)
    return by_uuid, by_id


def local_peer_jobs(store: JobStore, state_dir: Path, *, days: int = 7, limit: int = 100, now: Optional[float] = None) -> Dict[str, Any]:
    at = time.time() if now is None else float(now)
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 200))
    cutoff = at - days * DAY
    self_id, self_label = _self_identity(state_dir)
    conn = _open_carnivore_db(state_dir)
    titles: Dict[str, str] = {}
    if conn is not None:
        with closing(conn):
            titles, _ = _session_title_map(conn)
    with store._borrow() as jconn:  # noqa: SLF001
        rows = jconn.execute(
            "SELECT id, state, body, project_uid, project_name, caller_session, request_json, peer_install_id, peer_label, "
            "reason, exit_code, error_code, error_detail, task_head, agent_type, created_at, started_at, ended_at "
            "FROM jobs WHERE (created_at>=? OR state NOT IN ('here','done','failed','lost','stopped','refused')) "
            "ORDER BY created_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    out_jobs: List[Dict[str, Any]] = []
    for r in rows:
        jid = str(r["id"])
        if jid.startswith(WARM_PREFIX):
            continue
        try:
            req = json.loads(r["request_json"] or "{}").get("request", {})
        except ValueError:
            req = {}
        body = str(r["body"] or "command")
        head = _trim(r["task_head"] if body == "agent" else req.get("command"), 180)
        caller_uuid = str(r["caller_session"] or "") or None
        out_jobs.append({
            "id": jid,
            "state": str(r["state"]),
            "body": body,
            "project_uid": str(r["project_uid"] or ""),
            "project_name": str(r["project_name"] or ""),
            "title": head or ("agent worker" if body == "agent" else "command"),
            "agent_type": str(r["agent_type"] or "") or None,
            "target_install_id": str(r["peer_install_id"] or "") or None,
            "target_label": str(r["peer_label"] or "") or None,
            "reason": _trim(r["reason"] or r["error_detail"], 220) or None,
            "exit_code": r["exit_code"],
            "caller_session": caller_uuid,
            "caller_label": titles.get(caller_uuid, "") if caller_uuid else "",
            "created_at": float(r["created_at"]),
            "started_at": float(r["started_at"]) if r["started_at"] is not None else None,
            "ended_at": float(r["ended_at"]) if r["ended_at"] is not None else None,
        })
    return {"install_id": self_id, "label": self_label, "jobs": out_jobs}


def _load_local_parts(store: JobStore, state_dir: Path, *, days: int, limit: int, now: float) -> Dict[str, Any]:
    cutoff = now - days * DAY
    fleet = load_report._live_fleet()  # noqa: SLF001
    self_id, self_label = _self_identity(state_dir)
    computers: Dict[str, Dict[str, Any]] = {}
    host_key_to_comp: Dict[str, Tuple[str, str]] = {"local": (self_id, self_label)}
    for m in fleet.get("machines") or []:
        iid = str(m.get("install_id") or "")
        lbl = str(m.get("label") or iid)
        if not iid:
            continue
        if m.get("is_self"):
            self_id, self_label = iid, lbl
            host_key_to_comp["local"] = (iid, lbl)
        computers[iid] = {
            "install_id": iid,
            "label": lbl,
            "is_self": bool(m.get("is_self")),
            "state": str(m.get("state") or ("self" if m.get("is_self") else "offline")),
            "online": bool(m.get("online")),
            "cores": m.get("cores"),
            "cpu_pct": m.get("cpu_pct"),
            "cpu_headroom_cores": m.get("cpu_headroom_cores"),
            "mem_total_gb": m.get("mem_total_gb"),
            "mem_available_gb": m.get("mem_available_gb"),
            "ram_pct": m.get("ram_pct"),
            "mem_headroom_gb": m.get("mem_headroom_gb"),
            "pegged": bool(m.get("pegged")),
            "live_agents": 0,
            "live_commands": 0,
            "live_delegated_agents": 0,
            "live_total": 0,
            "history_agents": 0,
            "history_commands": 0,
            "history_delegated_agents": 0,
            "history_total": 0,
        }
    if self_id not in computers:
        computers[self_id] = {
            "install_id": self_id, "label": self_label, "is_self": True, "state": "self", "online": True,
            "cores": None, "cpu_pct": None, "cpu_headroom_cores": None, "mem_total_gb": None,
            "mem_available_gb": None, "ram_pct": None, "mem_headroom_gb": None, "pegged": False,
            "live_agents": 0, "live_commands": 0, "live_delegated_agents": 0, "live_total": 0,
            "history_agents": 0, "history_commands": 0, "history_delegated_agents": 0, "history_total": 0,
        }

    items: List[Dict[str, Any]] = []
    titles_by_uuid: Dict[str, str] = {}
    conn = _open_carnivore_db(state_dir)
    if conn is not None:
        with closing(conn):
            try:
                for hr in conn.execute("SELECT key, label, peer_install_id, kind, peer_state FROM hosts").fetchall():
                    hk = str(hr["key"] or "")
                    kind = str(hr["kind"] or "").lower()
                    if hk == "local" or kind == "local":
                        continue
                    iid = str(hr["peer_install_id"] or f"ssh:{hk}")
                    lbl = str(hr["label"] or hk)
                    if hk:
                        host_key_to_comp[hk] = (iid, lbl)
                    if iid not in computers and kind in ("peer", "ssh"):
                        computers[iid] = {
                            "install_id": iid, "label": lbl, "is_self": False,
                            "state": str(hr["peer_state"] or hr["kind"] or "offline"), "online": False,
                            "cores": None, "cpu_pct": None, "cpu_headroom_cores": None, "mem_total_gb": None,
                            "mem_available_gb": None, "ram_pct": None, "mem_headroom_gb": None, "pegged": False,
                            "live_agents": 0, "live_commands": 0, "live_delegated_agents": 0, "live_total": 0,
                            "history_agents": 0, "history_commands": 0, "history_delegated_agents": 0, "history_total": 0,
                        }
            except sqlite3.Error:
                pass
            try:
                for pm in conn.execute("SELECT install_id, host_key, label, is_self FROM pack_machines").fetchall():
                    iid = str(pm["install_id"] or "")
                    hk = str(pm["host_key"] or "")
                    lbl = str(pm["label"] or iid)
                    if hk and iid:
                        host_key_to_comp[hk] = (iid, lbl)
                    if iid and iid in computers and lbl:
                        computers[iid]["label"] = lbl
            except sqlite3.Error:
                pass

            titles_by_uuid, by_id = _session_title_map(conn)
            projects_by_id: Dict[int, str] = {}
            try:
                for pr in conn.execute("SELECT id, display_name, name FROM projects").fetchall():
                    projects_by_id[int(pr["id"])] = str(pr["display_name"] or pr["name"] or "")
            except sqlite3.Error:
                pass
            creators: Dict[str, str] = {}
            try:
                for cr in conn.execute("SELECT session_uuid, creator_uuid FROM session_creators").fetchall():
                    creators[str(cr["session_uuid"])] = str(cr["creator_uuid"])
            except sqlite3.Error:
                pass
            spawns: Dict[str, Tuple[str, str]] = {}
            try:
                for sr in conn.execute("SELECT child_uuid, parent_uuid, parent_kind FROM agent_spawn_links WHERE child_uuid IS NOT NULL").fetchall():
                    spawns[str(sr["child_uuid"])] = (str(sr["parent_uuid"] or ""), str(sr["parent_kind"] or "session"))
            except sqlite3.Error:
                pass
            placement_reasons: Dict[int, str] = {}
            try:
                for pl in conn.execute("SELECT session_id, reason FROM pack_placements WHERE session_id IS NOT NULL ORDER BY created_at DESC").fetchall():
                    sid = int(pl["session_id"])
                    if sid not in placement_reasons and pl["reason"]:
                        placement_reasons[sid] = _trim(pl["reason"], 220)
            except sqlite3.Error:
                pass
            try:
                srows = conn.execute(
                    "SELECT id, session_uuid, project_id, tmux_name, tmux_created_epoch, origin, agent_type, agent_family, "
                    "parent_session_id, lifecycle, last_seen_running_at, archived_at, title, claude_title, short_description, "
                    "activity_state, created_at, updated_at, host_key "
                    "FROM sessions ORDER BY created_at DESC LIMIT ?",
                    (max(limit * 3, 400),),
                ).fetchall()
            except sqlite3.Error:
                srows = []
            for sr in srows:
                d = dict(sr)
                if d.get("parent_session_id") is not None and not d.get("tmux_created_epoch") and d.get("origin") != "peer":
                    continue
                live, status_word, tone = _session_status(str(d.get("lifecycle") or ""), str(d.get("activity_state") or ""), d.get("archived_at"))
                started_at = _parse_ts(d.get("tmux_created_epoch")) or _parse_ts(d.get("created_at")) or now
                ended_at = None if live else (_parse_ts(d.get("last_seen_running_at")) or _parse_ts(d.get("updated_at")))
                if not live and started_at < cutoff and (ended_at is None or ended_at < cutoff):
                    continue
                suuid = str(d.get("session_uuid") or f"s-{d['id']}")
                hk = str(d.get("host_key") or "local")
                comp_id, comp_label = host_key_to_comp.get(hk, (hk, hk))
                parent_uuid: Optional[str] = None
                parent_kind = "owner"
                if suuid in spawns and spawns[suuid][0]:
                    parent_uuid, parent_kind = spawns[suuid]
                elif suuid in creators and creators[suuid]:
                    parent_uuid, parent_kind = creators[suuid], "session"
                elif d.get("parent_session_id") is not None and int(d["parent_session_id"]) in by_id:
                    parent_uuid, parent_kind = by_id[int(d["parent_session_id"])][0], "session"
                if parent_uuid:
                    starter_label = titles_by_uuid.get(parent_uuid) or parent_uuid[:8]
                    started_by = {"label": starter_label, "session_uuid": parent_uuid, "kind": parent_kind}
                else:
                    started_by = {"label": "owner", "session_uuid": None, "kind": "owner"}
                dur = max(0.0, (now if live else (ended_at or started_at)) - started_at)
                items.append({
                    "id": f"agent:{suuid}",
                    "item_type": "agent",
                    "live": live,
                    "status": status_word,
                    "tone": tone,
                    "title": _session_label(d),
                    "project": projects_by_id.get(int(d["project_id"]), "") if d.get("project_id") is not None else "",
                    "computer_id": comp_id,
                    "computer_label": comp_label,
                    "source_computer_label": None,
                    "started_by": started_by,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_s": round(dur, 1),
                    "agent_type": str(d.get("agent_family") or d.get("agent_type") or "agent"),
                    "reason": placement_reasons.get(int(d["id"])),
                    "session_uuid": suuid,
                    "job_id": None,
                    "can_stop": False,
                    "origin_scope": "local" if comp_id == self_id else "peer_session",
                })

    jobs_by_id: Dict[str, Dict[str, Any]] = {}
    with store._borrow() as jconn:  # noqa: SLF001
        jrows = jconn.execute(
            "SELECT * FROM jobs WHERE (created_at>=? OR state NOT IN ('here','done','failed','lost','stopped','refused')) "
            "ORDER BY created_at DESC LIMIT ?",
            (cutoff, max(limit * 2, 300)),
        ).fetchall()
        hrows = jconn.execute(
            "SELECT * FROM host_jobs WHERE job_id NOT LIKE ? AND "
            "(created_at>=? OR state IN ('preparing','running','parked')) ORDER BY created_at DESC LIMIT ?",
            (WARM_PREFIX + "%", cutoff, max(limit * 2, 200)),
        ).fetchall()

    for jr in jrows:
        jid = str(jr["id"])
        if jid.startswith(WARM_PREFIX):
            continue
        state = str(jr["state"])
        live = state not in _CALLER_DONE
        body = str(jr["body"] or "command")
        try:
            req = json.loads(jr["request_json"] or "{}").get("request", {})
        except ValueError:
            req = {}
        title = _trim(jr["task_head"] if body == "agent" else req.get("command"), 180) or (
            "agent worker" if body == "agent" else "command"
        )
        peer_id = str(jr["peer_install_id"] or "") or None
        peer_lbl = str(jr["peer_label"] or "") or None
        if state == "here" or not peer_id:
            comp_id, comp_label = self_id, self_label
        else:
            comp_id = peer_id
            comp_label = peer_lbl or computers.get(peer_id, {}).get("label") or peer_id
        caller_uuid = str(jr["caller_session"] or "") or None
        if caller_uuid:
            started_by = {"label": titles_by_uuid.get(caller_uuid) or caller_uuid[:8], "session_uuid": caller_uuid, "kind": "session"}
        else:
            started_by = {"label": "owner", "session_uuid": None, "kind": "owner"}
        started_at = float(jr["started_at"] or jr["created_at"])
        ended_at = float(jr["ended_at"]) if jr["ended_at"] is not None else None
        dur = max(0.0, (now if live else (ended_at or started_at)) - started_at)
        worker_listing = _listing_uuid(peer_id, jr["worker_session_uuid"]) if jr["worker_session_uuid"] else None
        jobs_by_id[jid] = {
            "id": f"job:{jid}",
            "item_type": "delegated_agent" if body == "agent" else "command",
            "live": live,
            "status": state,
            "tone": _job_tone(state, live),
            "title": title,
            "project": str(jr["project_name"] or ""),
            "computer_id": comp_id,
            "computer_label": comp_label,
            "source_computer_label": self_label if comp_id != self_id else None,
            "started_by": started_by,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_s": round(dur, 1),
            "agent_type": str(jr["agent_type"] or ("agent" if body == "agent" else "command")),
            "reason": _trim(jr["reason"] or jr["error_detail"], 220) or None,
            "session_uuid": worker_listing,
            "job_id": jid,
            "can_stop": live,
            "origin_scope": "local",
            "exit_code": jr["exit_code"],
        }

    for hr in hrows:
        jid = str(hr["job_id"])
        if jid in jobs_by_id:
            continue
        state = str(hr["state"])
        live = state in _HOST_LIVE
        body = str(hr["body"] or "command")
        sender_id = str(hr["caller_install"] or "")
        sender_lbl = computers.get(sender_id, {}).get("label") or sender_id or "peer"
        started_at = float(hr["started_at"] or hr["created_at"])
        ended_at = float(hr["ended_at"]) if hr["ended_at"] is not None else None
        dur = max(0.0, (now if live else (ended_at or started_at)) - started_at)
        jobs_by_id[jid] = {
            "id": f"job:{jid}",
            "item_type": "delegated_agent" if body == "agent" else "command",
            "live": live,
            "status": state,
            "tone": _job_tone(state, live),
            "title": "delegated agent" if body == "agent" else "delegated command",
            "project": "",
            "computer_id": self_id,
            "computer_label": self_label,
            "source_computer_label": sender_lbl,
            "started_by": {"label": sender_lbl, "session_uuid": None, "kind": "external"},
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_s": round(dur, 1),
            "agent_type": "agent" if body == "agent" else "command",
            "reason": _trim(hr["detail"], 220) or None,
            "session_uuid": str(hr["worker_session_uuid"] or "") or None,
            "job_id": jid,
            "can_stop": False,
            "origin_scope": "hosted",
            "exit_code": hr["exit_code"],
        }

    return {
        "self_id": self_id,
        "self_label": self_label,
        "computers": computers,
        "fleet_aggregate": fleet.get("aggregate"),
        "agent_items": items,
        "jobs_by_id": jobs_by_id,
        "report": load_report.build(store, days, now=now),
    }


async def _default_peer_fetch(install_id: str, days: int, limit: int) -> Optional[Dict[str, Any]]:
    from src.core.federation import peer_links
    from src.core.federation.peer_client import PeerRefused, PeerUnreachable

    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        return None
    try:
        status, body = await asyncio.wait_for(
            client.request("GET", f"/federation/pack/jobs/activity?days={int(days)}&limit={int(limit)}", timeout=PEER_ACTIVITY_TIMEOUT_S),
            timeout=PEER_ACTIVITY_TIMEOUT_S + 0.5,
        )
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    return body


async def build_activity(
    store: JobStore,
    state_dir: Path,
    *,
    days: int = 7,
    limit: int = 250,
    include_peers: bool = True,
    now: Optional[float] = None,
    peer_fetcher: Optional[Callable[[str, int, int], Awaitable[Optional[Dict[str, Any]]]]] = None,
) -> Dict[str, Any]:
    at = time.time() if now is None else float(now)
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 500))
    base = await asyncio.to_thread(_load_local_parts, store, state_dir, days=days, limit=limit, now=at)
    computers: Dict[str, Dict[str, Any]] = base["computers"]
    jobs_by_id: Dict[str, Dict[str, Any]] = base["jobs_by_id"]
    self_id: str = base["self_id"]

    peer_ids = [
        iid for iid, comp in computers.items()
        if not comp["is_self"] and comp["online"] and not iid.startswith("ssh:")
    ]
    fanout_ok = 0
    fanout_skipped = 0
    if include_peers and peer_ids:
        fetcher = peer_fetcher or _default_peer_fetch
        results = await asyncio.gather(*(fetcher(iid, days, min(limit, 150)) for iid in peer_ids), return_exceptions=True)
        for peer_iid, payload in zip(peer_ids, results):
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                fanout_skipped += 1
                continue
            fanout_ok += 1
            sender_lbl = str(payload.get("label") or computers.get(peer_iid, {}).get("label") or peer_iid)
            for pj in payload["jobs"]:
                if not isinstance(pj, dict) or not pj.get("id"):
                    continue
                jid = str(pj["id"])
                if jid.startswith(WARM_PREFIX):
                    continue
                if jid in jobs_by_id:
                    existing = jobs_by_id[jid]
                    if existing.get("origin_scope") == "hosted":
                        if pj.get("title"):
                            existing["title"] = _trim(pj["title"], 180)
                        if pj.get("project_name") and not existing.get("project"):
                            existing["project"] = str(pj["project_name"])
                        if pj.get("caller_label"):
                            existing["started_by"] = {
                                "label": f"{pj['caller_label']} ({sender_lbl})",
                                "session_uuid": None,
                                "kind": "external",
                            }
                        if pj.get("reason") and not existing.get("reason"):
                            existing["reason"] = _trim(pj["reason"], 220)
                    continue
                state = str(pj.get("state") or "done")
                live = state not in _CALLER_DONE
                body = str(pj.get("body") or "command")
                tgt_id = str(pj.get("target_install_id") or "")
                tgt_lbl = str(pj.get("target_label") or "")
                if state == "here" or not tgt_id:
                    comp_id, comp_label = peer_iid, sender_lbl
                else:
                    comp_id = tgt_id
                    comp_label = tgt_lbl or computers.get(tgt_id, {}).get("label") or tgt_id
                started_at = float(pj.get("started_at") or pj.get("created_at") or at)
                ended_at = float(pj["ended_at"]) if pj.get("ended_at") is not None else None
                dur = max(0.0, (at if live else (ended_at or started_at)) - started_at)
                caller_lbl = str(pj.get("caller_label") or "").strip()
                started_by = {
                    "label": f"{caller_lbl} ({sender_lbl})" if caller_lbl else sender_lbl,
                    "session_uuid": None,
                    "kind": "external",
                }
                jobs_by_id[jid] = {
                    "id": f"job:{jid}",
                    "item_type": "delegated_agent" if body == "agent" else "command",
                    "live": live,
                    "status": state,
                    "tone": _job_tone(state, live),
                    "title": _trim(pj.get("title"), 180) or ("agent worker" if body == "agent" else "command"),
                    "project": str(pj.get("project_name") or ""),
                    "computer_id": comp_id,
                    "computer_label": comp_label,
                    "source_computer_label": sender_lbl if comp_id != peer_iid else None,
                    "started_by": started_by,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_s": round(dur, 1),
                    "agent_type": str(pj.get("agent_type") or ("agent" if body == "agent" else "command")),
                    "reason": _trim(pj.get("reason"), 220) or None,
                    "session_uuid": None,
                    "job_id": jid,
                    "can_stop": False,
                    "origin_scope": "peer_to_peer",
                    "exit_code": pj.get("exit_code"),
                }

    all_items: List[Dict[str, Any]] = [*base["agent_items"], *jobs_by_id.values()]
    live_agents_total = 0
    live_jobs_total = 0
    history_total = 0
    for item in all_items:
        cid = str(item["computer_id"])
        if cid not in computers:
            computers[cid] = {
                "install_id": cid, "label": str(item["computer_label"] or cid), "is_self": cid == self_id,
                "state": "unknown", "online": False, "cores": None, "cpu_pct": None, "cpu_headroom_cores": None,
                "mem_total_gb": None, "mem_available_gb": None, "ram_pct": None, "mem_headroom_gb": None, "pegged": False,
                "live_agents": 0, "live_commands": 0, "live_delegated_agents": 0, "live_total": 0,
                "history_agents": 0, "history_commands": 0, "history_delegated_agents": 0, "history_total": 0,
            }
        comp = computers[cid]
        itype = item["item_type"]
        if item["live"]:
            comp["live_total"] += 1
            if itype == "agent":
                comp["live_agents"] += 1
                live_agents_total += 1
            elif itype == "delegated_agent":
                comp["live_delegated_agents"] += 1
                live_jobs_total += 1
            else:
                comp["live_commands"] += 1
                live_jobs_total += 1
        else:
            comp["history_total"] += 1
            history_total += 1
            if itype == "agent":
                comp["history_agents"] += 1
            elif itype == "delegated_agent":
                comp["history_delegated_agents"] += 1
            else:
                comp["history_commands"] += 1

    all_items.sort(key=lambda x: (1 if x["live"] else 0, float(x["started_at"] or 0.0)), reverse=True)
    comp_list = sorted(
        computers.values(),
        key=lambda c: (0 if c["is_self"] else (1 if c["online"] else 2), -(c["live_total"]), str(c["label"]).lower()),
    )
    rep = base["report"]
    agg = dict(base["fleet_aggregate"] or {})
    agg.update({
        "live_agents_total": live_agents_total,
        "live_jobs_total": live_jobs_total,
        "history_total": history_total,
        "peer_fanout": {"queried": len(peer_ids), "ok": fanout_ok, "skipped": fanout_skipped},
    })
    return {
        "days": days,
        "generated_at": at,
        "computers": comp_list,
        "fleet_aggregate": agg,
        "items": all_items[:limit],
        "total_items": len(all_items),
        "efficiency": rep.get("efficiency", {}),
        "guard_health": rep.get("guard_health", {}),
        "utilization_history": {
            "pegged_minutes_total": (rep.get("utilization_history") or {}).get("pegged_minutes_total", 0),
            "idle_while_peer_pegged_minutes": (rep.get("utilization_history") or {}).get("idle_while_peer_pegged_minutes", 0),
        },
        "summary": rep.get("summary", {}),
    }
