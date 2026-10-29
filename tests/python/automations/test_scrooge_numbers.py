from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.db import db_path_for
from src.core.automations.scrooge import numbers, rules
from src.core.stats import config, project_groups
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore
from tests.stats import seed

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
STAMP = int((NOW - timedelta(days=1)).timestamp()) // 60 * 60


def _snapshot(*roots: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for root in roots for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def _usage(db, conv, path, model, cost, kind="session"):
    seed.execute(db, "INSERT INTO minute_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (STAMP, "local", "claude", conv, project_key(str(path)), model, kind,
                  10, 0, 0, 5, cost, "v1", 1, 1, 0, "ok"))


def test_scrooge_numbers(tmp_path, monkeypatch):
    tmp = tmp_path.resolve()
    home = tmp / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    project_groups.forget()
    a, a_sub, b = tmp / "proj" / "A", tmp / "proj" / "A" / "web", tmp / "proj" / "B"
    c, d = tmp / "proj" / "C", tmp / "proj" / "D"
    fillers = [tmp / "proj" / f"F{i}" for i in range(10)]
    for folder in (a, a_sub, b, c, d, *fillers):
        folder.mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# Global\nUse python3\nNo  emojis\n---\nOnly global\n")
    (a / "CLAUDE.md").write_text("# Mine\nuse python3\nNo emojis\nNO EMOJIS  \n---\nonly a\nTabs rule\n")
    (a / "AGENTS.md").write_text("only a\nagents only\n")
    (tmp / "outside.md").write_text("secret\n")
    (b / "AGENTS.md").symlink_to(tmp / "outside.md")
    (b / "CLAUDE.md").write_bytes(b"x\n" * (rules.MAX_RULE_BYTES // 2 + 1))
    before = _snapshot(tmp / "proj", home)

    store = StatsStore(tmp / "state")
    store.initialize()
    config.ensure_schema(store)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    with sqlite3.connect(db_path_for(store.state_dir)) as db:
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, root TEXT, raw_path TEXT, display_name TEXT, "
                   "archived_at TEXT)")
        db.execute("CREATE TABLE sessions (project_id INTEGER, working_dir TEXT, last_work_at TEXT)")
        fresh, stale = (NOW - timedelta(days=2)).isoformat(), (NOW - timedelta(days=40)).isoformat()
        rows = [("A", a, None, fresh), ("B", b, None, fresh), ("C", c, "2026-01-01", fresh), ("D", d, None, stale)]
        rows += [(f"F{i}", f, "2026-01-01", fresh) for i, f in enumerate(fillers)]
        for pid, (name, path, archived, work) in enumerate(rows, start=1):
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (pid, str(path), str(path), name, archived))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (pid, str(path), work))
        db.execute("INSERT INTO sessions VALUES (1,?,?)", (str(a_sub), fresh))
    with store.connect() as db:
        _usage(db, "a-root", a, "claude-opus-4-1", 400_000_000_000)
        _usage(db, "a-agent", a, "claude-opus-4-1", 100_000_000_000, "subagent")
        _usage(db, "a-sub", a_sub, "claude-sonnet-4-5", 600_000_000_000)
        _usage(db, "b", b, "claude-sonnet-4-5", 5_000_000_000)
        _usage(db, "c", c, "claude-opus-4-1", 90_000_000_000)
        _usage(db, "d", d, "claude-opus-4-1", 50_000_000_000)
        for i, f in enumerate(fillers):
            _usage(db, f"f{i}", f, "claude-opus-4-1", (100 + i) * 1_000_000_000)
        seed.execute(db, "INSERT INTO minute_counters VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (STAMP, "local", "claude", "a-root", project_key(str(a)), "claude-opus-4-1", "session",
                      "thinking_tokens", "", 77))

    conn = sqlite3.connect(db_path_for(store.state_dir))
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 14
    assert len(project_groups.groups_for(store).labels) == 14

    started = time.monotonic()
    got = numbers.collect_numbers(store, conn, now=NOW, home=home)
    assert time.monotonic() - started < 5
    by_name = {p["name"]: p for p in got["projects"]}
    assert set(by_name) == {"A", "B"}
    assert got["scope"] == {"projects": 2, "excluded_archived": 11, "excluded_idle": 1, "excluded_remote": 0}
    assert by_name["A"]["est_cost_usd"] == 1100.0
    assert by_name["A"]["subagent_cost_usd"] == 100.0 and by_name["A"]["subagent_share_pct"] == 9.1
    assert by_name["A"]["thinking"] == 77
    assert by_name["A"]["root_folder_only"] is True
    assert by_name["A"]["model_mix"] == [{"model": "Opus 4.1", "share_pct": 100.0}]
    assert by_name["B"]["est_cost_usd"] == 5.0
    assert by_name["B"]["root_folder_only"] is True
    assert [p["name"] for p in got["projects"]] == ["A", "B"]
    assert len(got["levers"]) == 7
    assert [lv["id"] for lv in got["levers"]] == [f"L{i}" for i in range(1, 8)]
    assert {lv["id"]: lv["status"] for lv in got["levers"]}["L4"] == "not_measured"
    assert all(lv["reason"] for lv in got["levers"])

    globals_ = rules.read_global_rules()
    assert [g.label for g in globals_] == ["~/.claude/CLAUDE.md"]
    summary = rules.summarize_rules(rules.read_project_rules(a), globals_)
    shared = [o for o in summary["overlap"] if o["b"] == "~/.claude/CLAUDE.md"]
    assert shared == [{"a": "CLAUDE.md", "b": "~/.claude/CLAUDE.md", "shared_lines": 2, "shared_pct": 40.0}]
    in_folder = [o for o in summary["overlap"] if o["b"] == "AGENTS.md"]
    assert in_folder[0]["shared_lines"] == 1
    big = rules.summarize_rules(rules.read_project_rules(b), globals_)
    assert [(f["path"], f["oversize"]) for f in big["rule_files"]] == [("CLAUDE.md", True)]

    assert _snapshot(tmp / "proj", home) == before
