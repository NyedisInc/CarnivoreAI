
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.api import federation_pack_jobs_routes as fed_routes
from src.api import pack_jobs_metrics_routes as owner_routes
from src.core.mcp import pack_jobs_metrics_tools as mcp_tools
from src.core.pack.jobs import activity, boot
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import HostJob, HostState, JobRecord, JobState
from src.core.pack.machines import capabilities as pack_capabilities

NOW = 1_800_000_000.0
UID = "p1act123"


def _seed_carnivore_db(state_dir: Path) -> None:
    db_path = state_dir / "carnivore.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, name TEXT);
        CREATE TABLE hosts (key TEXT PRIMARY KEY, label TEXT, peer_install_id TEXT, kind TEXT, peer_state TEXT);
        CREATE TABLE pack_machines (install_id TEXT PRIMARY KEY, host_key TEXT, label TEXT, is_self INTEGER);
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, session_uuid TEXT, project_id INTEGER, tmux_name TEXT,
            tmux_created_epoch INTEGER, origin TEXT, agent_type TEXT, agent_family TEXT,
            parent_session_id INTEGER, lifecycle TEXT, last_seen_running_at TEXT,
            archived_at TEXT, title TEXT, claude_title TEXT, short_description TEXT,
            activity_state TEXT, created_at TEXT, updated_at TEXT, host_key TEXT
        );
        CREATE TABLE session_creators (session_uuid TEXT PRIMARY KEY, creator_uuid TEXT, created_at TEXT);
        CREATE TABLE agent_spawn_links (child_id TEXT PRIMARY KEY, child_uuid TEXT, parent_id TEXT, parent_uuid TEXT, parent_kind TEXT, spawned_at REAL);
        CREATE TABLE pack_placements (id INTEGER PRIMARY KEY, session_id INTEGER, reason TEXT, created_at REAL);
        """
    )
    conn.execute("INSERT INTO projects VALUES (1, 'Carnivore', 'carnivore')")
    conn.execute("INSERT INTO hosts VALUES ('local', 'this machine', NULL, 'local', NULL)")
    conn.execute("INSERT INTO hosts VALUES ('peer-b', 'host-b', 'iid-b', 'peer', 'connected')")
    conn.execute("INSERT INTO hosts VALUES ('peer-c', 'host-c', 'iid-c', 'peer', 'connected')")
    conn.execute("INSERT INTO pack_machines VALUES ('iid-a', 'local', 'host-a', 1)")
    conn.execute("INSERT INTO pack_machines VALUES ('iid-b', 'peer-b', 'host-b', 0)")
    conn.execute("INSERT INTO pack_machines VALUES ('iid-c', 'peer-c', 'host-c', 0)")
    conn.execute(
        "INSERT INTO sessions VALUES (1, 'u-parent', 1, 'cv_parent', ?, 'created', 'claude', 'claude', NULL, 'running', NULL, NULL, 'Cv-PackLoad', NULL, NULL, 'working', ?, ?, 'local')",
        (int(NOW - 600), str(NOW - 600), str(NOW - 10)),
    )
    conn.execute(
        "INSERT INTO sessions VALUES (4, 'u-idle-a', 1, 'cv_idle', ?, 'created', 'claude', 'claude', NULL, 'running', NULL, NULL, 'Idle-Agent', NULL, NULL, 'idle', ?, ?, 'local')",
        (int(NOW - 400), str(NOW - 400), str(NOW - 20)),
    )
    conn.execute(
        "INSERT INTO sessions VALUES (2, 'u-child-b', 1, 'cv_b_1', ?, 'peer', 'claude', 'claude', NULL, 'running', NULL, NULL, 'host-b-builder', NULL, NULL, 'working', ?, ?, 'peer-b')",
        (int(NOW - 300), str(NOW - 300), str(NOW - 5)),
    )
    conn.execute("INSERT INTO agent_spawn_links VALUES ('c1', 'u-child-b', 'p1', 'u-parent', 'session', ?)", (NOW - 300,))
    conn.execute("INSERT INTO pack_placements VALUES (1, 2, 'host-b had 8.2 cores free', ?)", (NOW - 300,))
    conn.execute(
        "INSERT INTO sessions VALUES (3, 'u-hist-c', 1, 'cv_c_1', ?, 'peer', 'codex', 'codex', NULL, 'stopped', ?, NULL, 'host-c-lint', NULL, NULL, 'idle', ?, ?, 'peer-c')",
        (int(NOW - 7200), str(NOW - 6900), str(NOW - 7200), str(NOW - 6900)),
    )
    conn.commit()
    conn.close()


def _fake_fleet() -> Dict[str, Any]:
    return {
        "machines": [
            {"install_id": "iid-a", "label": "host-a", "is_self": True, "state": "self", "online": True,
             "cores": 14, "cpu_pct": 42.0, "cpu_headroom_cores": 5.5, "mem_total_gb": 64.0, "mem_available_gb": 30.0,
             "ram_pct": 53.0, "mem_headroom_gb": 17.2, "pegged": False, "active_jobs": 1},
            {"install_id": "iid-b", "label": "host-b", "is_self": False, "state": "connected", "online": True,
             "cores": 10, "cpu_pct": 12.0, "cpu_headroom_cores": 7.8, "mem_total_gb": 16.0, "mem_available_gb": 8.0,
             "ram_pct": 50.0, "mem_headroom_gb": 6.4, "pegged": False, "active_jobs": 1},
            {"install_id": "iid-c", "label": "host-c", "is_self": False, "state": "connected", "online": True,
             "cores": 10, "cpu_pct": 5.0, "cpu_headroom_cores": 8.5, "mem_total_gb": 16.0, "mem_available_gb": 9.0,
             "ram_pct": 44.0, "mem_headroom_gb": 7.4, "pegged": False, "active_jobs": 0},
        ],
        "aggregate": {
            "online_machines": 3, "total_machines": 3, "total_cores": 34, "busy_cores": 7.6,
            "fleet_cpu_pct": 22.4, "usable_free_cores": 21.8, "total_ram_gb": 96.0, "used_ram_gb": 49.0,
            "fleet_ram_pct": 51.0, "usable_free_ram_gb": 31.0, "active_jobs": 2,
        },
    }


def test_build_activity_merges_sessions_jobs_peer_fanout_and_dedupes(tmp_path, monkeypatch) -> None:
    _seed_carnivore_db(tmp_path)
    store = JobStore(tmp_path)
    monkeypatch.setattr(activity.load_report, "_live_fleet", _fake_fleet)
    monkeypatch.setattr(activity, "_self_identity", lambda _sd: ("iid-a", "host-a"))

    store.create_job(JobRecord(
        id="job_local_0001", project_uid=UID, project_name="Carnivore", caller_session="u-parent",
        request_json=json.dumps({"request": {"command": "pytest -q tests/pack"}}),
        state=JobState.RUNNING, peer_install_id="iid-b", peer_label="host-b",
        reason="host-b scored higher (0.81 vs 0.62)", created_at=NOW - 120, updated_at=NOW - 10, started_at=NOW - 110,
    ))
    with store._tx() as conn:  # noqa: SLF001
        conn.execute(
            "INSERT INTO host_jobs (job_id, project_uid, caller_install, state, body, created_at, started_at, ended_at, exit_code) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("job_from_b1", UID, "iid-b", HostState.EXITED.value, "command", NOW - 500, NOW - 490, NOW - 430, 0),
        )

    async def fake_fetch(iid: str, days: int, limit: int) -> Optional[Dict[str, Any]]:
        if iid == "iid-b":
            return {
                "install_id": "iid-b",
                "label": "host-b",
                "jobs": [
                    {
                        "id": "job_from_b1", "state": "done", "body": "command", "project_uid": UID,
                        "project_name": "Carnivore", "title": "npm run build", "target_install_id": "iid-a",
                        "target_label": "host-a", "caller_label": "host-b-builder", "reason": "host-a had room",
                        "created_at": NOW - 500, "started_at": NOW - 490, "ended_at": NOW - 430,
                    },
                    {
                        "id": "job_p2p_c001", "state": "running", "body": "agent", "project_uid": UID,
                        "project_name": "Carnivore", "title": "review pack diff", "agent_type": "claude",
                        "target_install_id": "iid-c", "target_label": "host-c", "caller_label": "host-b-builder",
                        "reason": "host-c was idle", "created_at": NOW - 90, "started_at": NOW - 85, "ended_at": None,
                    },
                ],
            }
        return None

    out = asyncio.run(activity.build_activity(store, tmp_path, days=7, limit=100, include_peers=True, now=NOW, peer_fetcher=fake_fetch))

    assert out["fleet_aggregate"]["peer_fanout"] == {"queried": 2, "ok": 1, "skipped": 1}

    by_id = {it["id"]: it for it in out["items"]}
    assert len(by_id) == len(out["items"])
    assert by_id["agent:u-child-b"]["computer_label"] == "host-b"
    assert by_id["agent:u-child-b"]["started_by"]["label"] == "Cv-PackLoad"
    assert by_id["agent:u-child-b"]["reason"] == "host-b had 8.2 cores free"
    assert by_id["job:job_local_0001"]["computer_label"] == "host-b"
    assert by_id["job:job_local_0001"]["started_by"]["label"] == "Cv-PackLoad"
    assert by_id["job:job_local_0001"]["can_stop"] is True
    assert by_id["job:job_from_b1"]["title"] == "npm run build"
    assert by_id["job:job_from_b1"]["started_by"]["label"] == "host-b-builder (host-b)"
    p2p = by_id["job:job_p2p_c001"]
    assert p2p["origin_scope"] == "peer_to_peer"
    assert p2p["computer_label"] == "host-c"
    assert p2p["source_computer_label"] == "host-b"
    assert p2p["live"] is True

    comps = {c["install_id"]: c for c in out["computers"]}
    assert "ssh:local" not in comps
    assert comps["iid-a"]["live_agents"] == 2 and comps["iid-a"]["history_commands"] == 1
    assert comps["iid-b"]["live_agents"] == 1 and comps["iid-b"]["live_commands"] == 1
    assert comps["iid-c"]["live_delegated_agents"] == 1 and comps["iid-c"]["history_agents"] == 1

    assert (by_id["agent:u-parent"]["status"], by_id["agent:u-parent"]["tone"]) == ("working", "ok")
    assert (by_id["agent:u-idle-a"]["status"], by_id["agent:u-idle-a"]["tone"]) == ("idle", "neutral")
    assert (by_id["job:job_local_0001"]["status"], by_id["job:job_local_0001"]["tone"]) == ("running", "ok")


def test_local_peer_jobs_capability_and_mcp_spec(tmp_path, monkeypatch) -> None:
    _seed_carnivore_db(tmp_path)
    store = JobStore(tmp_path)
    monkeypatch.setattr(activity, "_self_identity", lambda _sd: ("iid-a", "host-a"))
    store.create_job(JobRecord(
        id="job_peer_0001", project_uid=UID, project_name="Carnivore", caller_session="u-parent",
        request_json=json.dumps({"request": {"command": "pytest -q " + "x" * 300}}),
        state=JobState.DONE, peer_install_id="iid-b", peer_label="host-b",
        created_at=NOW - 60, updated_at=NOW - 10, started_at=NOW - 55, ended_at=NOW - 10,
    ))
    snap = activity.local_peer_jobs(store, tmp_path, days=7, limit=50, now=NOW)
    assert snap["install_id"] == "iid-a" and snap["label"] == "host-a"
    assert len(snap["jobs"]) == 1
    assert snap["jobs"][0]["caller_label"] == "Cv-PackLoad"
    assert len(snap["jobs"][0]["title"]) <= 180

    assert activity.CAP_ACTIVITY in pack_capabilities.names()

    spec = [s for s in mcp_tools.SPECS if s.name == "pack_activity_get"][0]
    seen: Dict[str, Any] = {}
    spec.invoke(SimpleNamespace(route=lambda **kw: seen.update(kw), args={"days": 14, "limit": 40, "include_peers": False}))
    assert seen == {"days": 14, "limit": 40, "include_peers": False}
