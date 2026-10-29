
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.computers import add_over_ssh, store
from src.core.federation import peer_hosts

FID_SHORT_LEN = 6
UNREACHABLE_NOTE_HOURS = 24
_GONE_STATES = ("disconnected", "unpaired")


def iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(rt: Any, links: Any, row: Optional[store.LinkRow], iid: str) -> str:
    live = links.state(iid) if links is not None else "disconnected"
    if row is not None and row.role == "member" and rt.listener is not None and iid in rt.listener.connected():
        live = "connected"
    if row is not None and row.provisional and live != "connected":
        return "waiting_first_link"
    return live


def _duplicates(computers: List[Dict[str, Any]]) -> None:
    for entry in computers:
        if entry["state"] not in _GONE_STATES:
            continue
        label = (entry["label"] or "").strip().lower()
        for other in computers:
            if other is entry or (other["label"] or "").strip().lower() != label:
                continue
            if other["state"] not in _GONE_STATES or (other["joined_at"] or "") > (entry["joined_at"] or ""):
                entry["possible_duplicate_of"] = other["install_id"]
                break


def _dial(rt: Any, row: Optional[store.LinkRow]) -> Optional[Dict[str, Any]]:
    dialer = rt.dialer
    if row is None or row.role != "member" or row.transport != "tls" or dialer is None:
        return None
    dial = dialer.dial_state(row.peer_install_id)
    return None if dial is None else {"state": dial["state"], "since": iso(dial["since"])}


def computer_entry(rt: Any, links: Any, row: Optional[store.LinkRow], host: Optional[peer_hosts.PeerRow]) -> Dict[str, Any]:
    iid = row.peer_install_id if row is not None else host.peer_install_id  # type: ignore[union-attr]
    fid = host.peer_fid if host is not None else ""
    return {
        "install_id": iid,
        "label": host.label if host is not None else iid[:8],
        "host_key": host.key if host is not None else None,
        "transport": row.transport if row is not None else "ssh",
        "role": row.role if row is not None else "peer",
        "state": _state(rt, links, row, iid),
        "direction": "one_way" if row is not None and row.inbound_control == 0 else "both",
        "fid": fid,
        "fid_short": (fid or (row.link_fid if row is not None and row.link_fid else ""))[:FID_SHORT_LEN],
        "cert_sha256": row.cert_sha256 if row is not None else None,
        "joined_at": row.joined_at if row is not None else None,
        "last_link_at": row.last_link_at if row is not None else None,
        "possible_duplicate_of": None,
        "dial": _dial(rt, row),
        "firewall_on": add_over_ssh.JOBS.firewall_on(iid),
    }


def _main_note(entry: Dict[str, Any]) -> bool:
    if entry["state"] == "connected" or entry["last_link_at"] is None:
        return False
    try:
        last = datetime.strptime(entry["last_link_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last > timedelta(hours=UNREACHABLE_NOTE_HOURS)


def read_computers(conn: sqlite3.Connection, rt: Any, links: Any) -> List[Dict[str, Any]]:
    rows = {r.peer_install_id: r for r in store.list_rows(conn)}
    hosts = {h.peer_install_id: h for h in peer_hosts.list_peers(conn)}
    out = [computer_entry(rt, links, rows.get(iid), hosts.get(iid)) for iid in dict.fromkeys([*rows, *hosts])]
    _duplicates(out)
    return out


def _member_link(rt: Any) -> Dict[str, Any]:
    ml = rt.member_listener
    if ml is None or ml.state == "stopped":
        return {"state": "off", "port": None}
    return {"state": ml.state, "port": ml.port}


def build_view(rt: Any, links: Any) -> Dict[str, Any]:
    with closing(rt.open_db()) as conn:
        computers = read_computers(conn, rt, links)
    main = next((c for c in computers if c["role"] == "main" and c["transport"] == "tls"), None)
    has_members = any(c["role"] == "member" and c["transport"] == "tls" for c in computers)
    role = "member" if main is not None else "main" if has_members else "standalone"
    state = rt.link_state
    live = rt.invites.live() if rt.invites is not None else []
    fid = rt.fed_key.device_id if rt.fed_key is not None else ""
    return {
        "self": {
            "install_id": rt.iid, "label": rt.label, "fid_short": fid[:FID_SHORT_LEN], "role": role,
            "link": {"state": _member_link(rt)["state"] if role == "member" else "off" if state == "stopped" else state,
                     "port": _member_link(rt)["port"] if role == "member" else rt.link_port,
                     "join_open": bool(rt.join_server is not None and rt.join_server.port is not None),
                     "addresses": list(rt.addresses) if role != "member" else [],
                     "code_paused_until": iso(rt.invites.code_paused_until) if rt.invites is not None and rt.invites.code_paused() else None},
            "main": ({"label": main["label"], "state": main["state"], "last_link_at": main["last_link_at"], "reachable_note": _main_note(main)}
                     if main is not None else None),
        },
        "computers": computers,
        "invites": [{"id": i.id, "kind": i.kind, "code_live": i.code is not None, "expires_at": iso(i.expires_at),
                     "attempts_left": i.attempts_left} for i in live],
        "add_jobs": add_over_ssh.JOBS.snapshot(),
    }
