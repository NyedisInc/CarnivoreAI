
from __future__ import annotations

import random
import sqlite3
from typing import List

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.hosts import remote_project as new
from tests.python.federation import old_remote_project_reference as old

DDL = ("CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, root TEXT UNIQUE NOT NULL, raw_path TEXT, display_name TEXT, "
       "source TEXT, presence TEXT, host_key TEXT, created_at TEXT, updated_at TEXT, last_opened_at TEXT, uid TEXT UNIQUE)")
UIDS = [f"{i:032x}" for i in range(1, 6)] + ["bad", None, "A" * 32]
HOSTS, DIRS = ["h1", "h2"], ["/a", "/b", "/c"]
SEEDS = 400


def _run(mod, seed: int) -> list:
    rng = random.Random(seed)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute(DDL)
    for i in range(rng.randint(0, 6)):
        host, folder = rng.choice(HOSTS), rng.choice(DIRS)
        try:
            conn.execute("INSERT INTO projects (root, display_name, host_key, uid) VALUES (?,?,?,?)",
                         (f"peer://{host}{folder}", f"n{i}", rng.choice(HOSTS + [None]), rng.choice(UIDS[:5] + [None])))
        except sqlite3.IntegrityError:
            pass
    out: list = []
    claimed: set = set()
    for _ in range(rng.randint(1, 8)):
        if rng.random() < 0.3:
            claimed = set()
        host, folder = rng.choice(HOSTS), rng.choice(DIRS)
        b = mod.bind_remote_project(conn, host, folder, now="2026-01-01T00:00:00Z", root=f"peer://{host}{folder}",
                                    project_uid=rng.choice(UIDS), claimed=claimed)
        out.append((b.project_id, b.rule, b.root, b.created_project, b.attribution, tuple(sorted(claimed))))
    out.append(list(conn.execute("SELECT id, root, display_name, host_key, uid FROM projects ORDER BY id")))
    return out


def _mismatches() -> List[int]:
    return [s for s in range(SEEDS) if _run(old, s) != _run(new, s)]


def test_bind_remote_project_matches_the_frozen_reference() -> None:
    assert _mismatches() == []


def test_the_differential_goes_red_when_a_retag_is_reported_as_a_match(monkeypatch) -> None:
    real = new._ladder

    def broken(*args, **kwargs):
        kind, pid, root = real(*args, **kwargs)
        return ("found" if kind == "retag" else kind), pid, root

    monkeypatch.setattr(new, "_ladder", broken)
    assert _mismatches() != []
