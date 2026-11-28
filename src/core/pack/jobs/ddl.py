
from __future__ import annotations

import sqlite3
from typing import Tuple

FILENAME = "pack-jobs.db"

DDL: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, idem_key TEXT NOT NULL DEFAULT '', project_uid TEXT NOT NULL DEFAULT '',
        project_name TEXT NOT NULL DEFAULT '', caller_session TEXT, request_json TEXT NOT NULL DEFAULT '{}',
        state TEXT NOT NULL, peer_install_id TEXT, peer_label TEXT, reason TEXT, scope TEXT,
        snapshot_commit TEXT, snapshot_tree TEXT, snapshot_at REAL, result_commit TEXT, exit_code INTEGER,
        output_tail TEXT, land_json TEXT, error_code TEXT, error_detail TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, started_at REAL, ended_at REAL)""",
    "CREATE INDEX IF NOT EXISTS jobs_idem ON jobs(idem_key)",
    "CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_uid, created_at)",
    """CREATE TABLE IF NOT EXISTS job_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, id)",
    """CREATE TABLE IF NOT EXISTS project_policy (
        project_uid TEXT PRIMARY KEY, auto_delegate INTEGER NOT NULL DEFAULT 0, never_use_json TEXT,
        carry_json TEXT, bring_back_json TEXT, setup_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS auto_replicas (
        project_uid TEXT NOT NULL, install_id TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY (project_uid, install_id))""",
    """CREATE TABLE IF NOT EXISTS host_jobs (
        job_id TEXT PRIMARY KEY, caller_install TEXT NOT NULL DEFAULT '', project_uid TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL, slot_path TEXT, snapshot_commit TEXT, result_commit TEXT, result_blob_id TEXT,
        exit_code INTEGER, time_cap_s INTEGER NOT NULL DEFAULT 3600, keep_until REAL, detail TEXT,
        created_at REAL NOT NULL, started_at REAL, ended_at REAL)""",
    """CREATE TABLE IF NOT EXISTS slots (
        path TEXT PRIMARY KEY, project_uid TEXT NOT NULL, slot INTEGER NOT NULL, repo_root TEXT NOT NULL DEFAULT '',
        job_id TEXT, memo_json TEXT, last_used REAL NOT NULL DEFAULT 0, keep_until REAL)""",
    "CREATE INDEX IF NOT EXISTS slots_project ON slots(project_uid, slot)",
    """CREATE TABLE IF NOT EXISTS peer_bases (
        project_uid TEXT NOT NULL, peer_install_id TEXT NOT NULL, commit_sha TEXT NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY (project_uid, peer_install_id))""",
    """CREATE TABLE IF NOT EXISTS detached_copies (
        project_uid TEXT NOT NULL, install_id TEXT NOT NULL, root TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY (project_uid, install_id))""",
    """CREATE TABLE IF NOT EXISTS project_needs (
        project_uid TEXT NOT NULL, kind TEXT NOT NULL, needs_json TEXT NOT NULL DEFAULT '[]', prefer_json TEXT NOT NULL DEFAULT '[]',
        updated_at REAL NOT NULL, PRIMARY KEY (project_uid, kind))""",
    """CREATE TABLE IF NOT EXISTS sync_state (
        project_uid TEXT NOT NULL, peer TEXT NOT NULL, refs_digest TEXT NOT NULL DEFAULT '', warm_commit TEXT NOT NULL DEFAULT '',
        last_ok REAL NOT NULL DEFAULT 0, last_try REAL NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (project_uid, peer))""",
    """CREATE TABLE IF NOT EXISTS tool_installs (
        id TEXT PRIMARY KEY, tool TEXT NOT NULL, formula TEXT NOT NULL, caller_install TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL, exit_code INTEGER, tail TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS heavy_episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, project_uid TEXT NOT NULL, minutes REAL NOT NULL,
        outcome TEXT NOT NULL, at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS load_hours (
        hour INTEGER PRIMARY KEY, busy_pct REAL, pegged_minutes REAL NOT NULL DEFAULT 0, max_run_queue_per_core REAL,
        mem_warn_minutes REAL NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS command_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_uid TEXT NOT NULL, shape TEXT NOT NULL, seconds REAL NOT NULL, at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS command_runs_shape ON command_runs(project_uid, shape, id)",
    """CREATE TABLE IF NOT EXISTS guard_giveways (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, project_uid TEXT NOT NULL, shape TEXT NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS schema_marks (name TEXT PRIMARY KEY)",
)

ADDED_COLUMNS = {
    "host_jobs": (
        ("body", "TEXT DEFAULT 'command'"), ("worker_session_id", "TEXT"), ("worker_session_uuid", "TEXT"), ("worker_tmux", "TEXT"),
        ("worker_epoch", "INTEGER"), ("family", "TEXT"), ("permission_mode", "TEXT"), ("account_label", "TEXT"), ("account_how", "TEXT"),
        ("parked_at", "REAL"), ("question", "TEXT"), ("question_kind", "TEXT"), ("result_text", "TEXT"), ("usage_json", "TEXT"),
        ("replied_at", "REAL"),
    ),
    "jobs": (
        ("body", "TEXT DEFAULT 'command'"), ("task_head", "TEXT"), ("agent_type", "TEXT"), ("family", "TEXT"), ("permission_mode", "TEXT"),
        ("account_label", "TEXT"), ("account_how", "TEXT"), ("result_text", "TEXT"), ("question", "TEXT"), ("question_kind", "TEXT"),
        ("usage_json", "TEXT"), ("notified_state", "TEXT"), ("worker_session_uuid", "TEXT"),
    ),
    "command_runs": (
        ("cpu_s", "REAL"), ("peak_ram_gb", "REAL"), ("source", "TEXT DEFAULT 'local'"),
    ),
    "project_policy": (
        ("local_only_json", "TEXT"),
    ),
}


def migrate(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name in have:
                continue
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc):
                    raise
    if conn.execute("INSERT OR IGNORE INTO schema_marks (name) VALUES ('wipe_slow_command_runs_2026_11_20')").rowcount:
        conn.execute("DELETE FROM command_runs WHERE seconds>=60")
    if conn.execute("INSERT OR IGNORE INTO schema_marks (name) VALUES ('wipe_poisoned_shapes_2026_11_23')").rowcount:
        conn.execute(
            "DELETE FROM command_runs WHERE shape LIKE 'cut%' OR shape LIKE 'tr %' OR shape = 'tr' "
            "OR shape LIKE 'seq %' OR shape LIKE 'export %' OR shape LIKE 'set %' OR shape = 'break' "
            "OR shape LIKE 'timeout %' OR shape LIKE 'gtimeout %' OR shape LIKE 'shasum%' OR shape LIKE 'sysctl%' "
            "OR shape = 'python3 -' OR shape LIKE 'gofmt %'"
        )
MADE_COPIES_DDL = """CREATE TABLE IF NOT EXISTS made_copies (
        root TEXT PRIMARY KEY, project_uid TEXT NOT NULL DEFAULT '', home_install_id TEXT NOT NULL DEFAULT '',
        auto INTEGER NOT NULL DEFAULT 0, folder_made INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT '')"""
DDL = DDL + (MADE_COPIES_DDL,)

SESSION_PLACE_DDL = (
    """CREATE TABLE IF NOT EXISTS session_placements (
        request_id TEXT PRIMARY KEY, project_uid TEXT NOT NULL DEFAULT '', install_id TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL DEFAULT '', session_id TEXT, session_uuid TEXT, reason TEXT NOT NULL DEFAULT '',
        starter_kind TEXT NOT NULL DEFAULT 'owner', created_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS session_placements_project ON session_placements(project_uid, created_at)",
    """CREATE TABLE IF NOT EXISTS automation_placement (
        automation_id TEXT PRIMARY KEY, placement TEXT NOT NULL DEFAULT 'here', updated_at REAL NOT NULL)""",
)
DDL = DDL + SESSION_PLACE_DDL

HOST_SESSION_PLACE_DDL = (
    """CREATE TABLE IF NOT EXISTS host_session_places (
        request_id TEXT PRIMARY KEY, caller_install TEXT NOT NULL DEFAULT '', project_uid TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL DEFAULT '',
        session_uuid TEXT, answer TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL)""",
)
DDL = DDL + HOST_SESSION_PLACE_DDL
SSH_DDL = (
    """CREATE TABLE IF NOT EXISTS ssh_targets (
        host_key TEXT PRIMARY KEY, takes_work INTEGER NOT NULL DEFAULT 0, pinned_fp TEXT, far_root TEXT, login_shell TEXT,
        path_extra_json TEXT, can_json TEXT, probed_at REAL, reserve_json TEXT, labels_json TEXT, last_ok REAL, last_error TEXT,
        updated_at REAL)""",
    """CREATE TABLE IF NOT EXISTS ssh_seeds (
        project_uid TEXT NOT NULL, host_key TEXT NOT NULL, head TEXT NOT NULL DEFAULT '', seeded_at REAL NOT NULL,
        PRIMARY KEY (project_uid, host_key))""",
)
DDL = DDL + SSH_DDL

LOAD_BALANCE_DDL = (
    """CREATE TABLE IF NOT EXISTS peer_overhead (
        project_uid TEXT NOT NULL, peer_install_id TEXT NOT NULL, ewma_s REAL NOT NULL, samples INTEGER NOT NULL DEFAULT 0,
        last_mirror_s REAL NOT NULL DEFAULT 0, last_bundle_bytes INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
        PRIMARY KEY (project_uid, peer_install_id))""",
    """CREATE TABLE IF NOT EXISTS machine_load_hours (
        install_id TEXT NOT NULL, hour INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', cores INTEGER, mem_total_gb REAL,
        busy_cpu_sum REAL NOT NULL DEFAULT 0, busy_cpu_n INTEGER NOT NULL DEFAULT 0, busy_cpu_max REAL,
        used_ram_sum REAL NOT NULL DEFAULT 0, used_ram_n INTEGER NOT NULL DEFAULT 0, used_ram_max REAL,
        avail_ram_sum REAL NOT NULL DEFAULT 0, pegged_ticks INTEGER NOT NULL DEFAULT 0, mem_warn_ticks INTEGER NOT NULL DEFAULT 0,
        idle_while_pegged_ticks INTEGER NOT NULL DEFAULT 0, jobs_hosted INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (install_id, hour))""",
    "CREATE INDEX IF NOT EXISTS machine_load_hours_hour ON machine_load_hours(hour)",
    """CREATE TABLE IF NOT EXISTS guard_events (
        day TEXT NOT NULL, outcome TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, outcome))""",
    """CREATE TABLE IF NOT EXISTS shape_overrides (
        project_uid TEXT NOT NULL, shape TEXT NOT NULL, mode TEXT NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY (project_uid, shape))""",
)
DDL = DDL + LOAD_BALANCE_DDL
