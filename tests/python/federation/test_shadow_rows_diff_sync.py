
from __future__ import annotations

import random
import re
import sqlite3
from contextlib import closing

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, shadow_rows, shadow_rows_diff
from src.core.pack.machines import capabilities

UIDS = [f"{i:032x}" for i in range(1, 6)]
DIRS = ["/w/a", "/w/b", "/w/c", "/w/d", "/w/e"]
LOCAL_DIRS = ["/local/x", "/local/y"]
PEERS = [("iid-a", "studio"), ("iid-b", "lab")]
SLEEP = sorted(shadow_rows.SLEEP_SOURCES)[0]


class Pair:

    def __init__(self, tmp_path, monkeypatch):
        self.monkeypatch, self.stamp, self.conns, self.keys = monkeypatch, [0], [], []
        for tag in ("a", "b"):
            folder = tmp_path / tag
            folder.mkdir()
            ensure_db_migrated(folder)
            conn = connect(db_path_for(folder), create=False)
            self.conns.append(conn)
            self.keys = [peer_hosts.upsert(conn, install_id=iid, label=label, grant_id="g" + iid, fid="f" + iid, initiator=True).key
                         for iid, label in PEERS]
        monkeypatch.setattr(shadow_rows, "utc_now", lambda: f"2026-11-22T00:{self.stamp[0] // 60:02d}:{self.stamp[0] % 60:02d}Z")

    def close(self) -> None:
        for conn in self.conns:
            conn.close()

    def sync(self, peer: int, rows, complete=True, asleep=None):
        self.stamp[0] += 1
        results = []
        for on, conn in zip((False, True), self.conns):
            self.monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
            results.append(shadow_rows.sync_peer(conn, host_key=self.keys[peer], peer_install_id=PEERS[peer][0],
                                                 rows=[dict(r) for r in rows], complete=complete,
                                                 asleep=None if asleep is None else [dict(r) for r in asleep]))
        return results

    def both(self, sql: str, args: tuple = ()) -> None:
        outcomes = []
        for conn in self.conns:
            try:
                conn.execute(sql, args)
                outcomes.append(None)
            except sqlite3.IntegrityError as exc:
                outcomes.append(str(exc))
        assert outcomes[0] == outcomes[1]

    def differ(self) -> str:
        keep = tuple(f'INSERT INTO "{t}"' for t in ("sessions", "peer_sessions", "projects", "swarm_agents", "sqlite_sequence"))
        mask = lambda ln: re.sub(r"'[0-9a-f]{32}'", lambda m: m.group(0) if m.group(0).strip("'") in UIDS else "'<random>'", ln)  # noqa: E731
        dumps = [[mask(ln) for ln in "\n".join(c.iterdump()).splitlines() if ln.startswith(keep)] for c in self.conns]
        if dumps[0] == dumps[1]:
            return ""
        return next((f"{x!r} != {y!r}" for x, y in zip(dumps[0], dumps[1]) if x != y), "length differs")


def frame_row(i: int, rng: random.Random) -> dict:
    return {"session_uuid": f"u{i}", "row_id": i + 1, "name": f"carnivore_n{i}", "working_dir": rng.choice(DIRS),
            "label": rng.choice(["api", "web", None]), "agent_type": rng.choice(["claude", "codex", None]),
            "agent_family": rng.choice(["claude", None]), "agent_family_source": rng.choice(["launch", None]),
            "project_uid": rng.choice([None, None, UIDS[0], UIDS[1], UIDS[2], "not-a-uid"])}


def mutate_frame(frame: dict, rng: random.Random, pool: int) -> None:
    for _ in range(rng.randint(1, 4)):
        i = rng.randrange(pool)
        op = rng.choice(["add", "add", "remove", "rename", "label", "agent", "dir", "uid", "bad", "uid_collide"])
        if op == "add" or i not in frame:
            frame[i] = frame_row(i, rng)
        elif op == "remove":
            del frame[i]
        elif op == "rename":
            frame[i]["name"] = f"carnivore_r{rng.randrange(99)}"
        elif op == "label":
            frame[i]["label"] = rng.choice(["api", "web", "db", None])
        elif op == "agent":
            frame[i]["agent_type"], frame[i]["agent_family_source"] = rng.choice(["claude", "codex"]), rng.choice(["launch", "hook", None])
        elif op == "dir":
            frame[i]["working_dir"] = rng.choice(DIRS)
        elif op == "uid":
            frame[i]["project_uid"] = rng.choice([None, UIDS[3], UIDS[4]])
        elif op == "uid_collide":
            for row in frame.values():
                row["project_uid"] = UIDS[0]
        else:
            frame[i]["name"] = ""


def local_change(pair: Pair, rng: random.Random, step: int) -> None:
    op = rng.choice(["create", "move", "rename", "uid", "home", "orphan", "age", "none", "none"])
    n = rng.randrange(4)
    if op == "create":
        root = f"peer://{pair.keys[rng.randrange(2)]}{rng.choice(DIRS)}"
        pair.both("INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, created_at, updated_at) "
                  "VALUES (?, ?, ?, 'user', 'present', ?, 't', 't')", (root, root, f"loc{step}", pair.keys[0]))
    elif op == "move":
        pair.both("UPDATE projects SET root = ? WHERE id = (SELECT id FROM projects WHERE root LIKE 'peer://%' ORDER BY id LIMIT 1 OFFSET ?)",
                  (f"peer://{pair.keys[0]}{rng.choice(DIRS)}x{step}", n))
    elif op == "rename":
        pair.both("UPDATE projects SET display_name = ? WHERE id = (SELECT id FROM projects ORDER BY id LIMIT 1 OFFSET ?)", (f"n{step}", n))
    elif op == "uid":
        pair.both("UPDATE projects SET uid = ? WHERE id = (SELECT id FROM projects ORDER BY id LIMIT 1 OFFSET ?)", (rng.choice(UIDS), n))
    elif op == "home":
        pair.both("INSERT OR IGNORE INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at) "
                  "VALUES (?, ?, 'home', 'adoption', 'present', 't', 't')", (LOCAL_DIRS[0], LOCAL_DIRS[0]))
        pair.both("INSERT INTO sessions (session_uuid, project_id, working_dir, tmux_socket, tmux_name, origin, lifecycle, host_key, "
                  "created_at, updated_at) VALUES (?, (SELECT id FROM projects WHERE root = ?), '/w', 'cloude', ?, 'created', 'stopped', "
                  "'local', 't', 't')", (f"u{rng.randrange(8)}", LOCAL_DIRS[0], f"loc_{step}"))
    elif op == "orphan":
        pair.both("DELETE FROM peer_sessions WHERE rowid = (SELECT rowid FROM peer_sessions ORDER BY rowid LIMIT 1 OFFSET ?)", (n,))
    elif op == "age":
        pair.both("UPDATE sessions SET updated_at = '2000-01-01T00:00:00Z' WHERE origin = 'peer' AND lifecycle = 'stopped' AND id % 2 = ?", (n % 2,))


def run_script(pair: Pair, seed: int, steps: int, pool: int = 12) -> str:
    rng = random.Random(seed)
    frames, asleep = [{}, {}], [{}, {}]
    for step in range(steps):
        for peer in range(2):
            mutate_frame(frames[peer], rng, pool)
            if rng.random() < 0.4:
                i = rng.randrange(pool)
                asleep[peer][i] = {**frame_row(i, rng), "source": SLEEP}
            if rng.random() < 0.2 and asleep[peer]:
                del asleep[peer][rng.choice(sorted(asleep[peer]))]
        local_change(pair, rng, step)
        for peer in rng.sample(range(2), rng.choice([1, 2])):
            rows = list(frames[peer].values())
            if rng.random() < 0.15 and rows:
                rows.append(dict(rows[0]))
            use_asleep = None if rng.random() < 0.2 else list(asleep[peer].values())
            old, new = pair.sync(peer, rows, complete=rng.random() < 0.7, asleep=use_asleep)
            if old != new:
                return f"seed {seed} step {step}: results {old} != {new}"
            if (why := pair.differ()):
                return f"seed {seed} step {step}: {why}"
    return ""


@pytest.fixture()
def pair(tmp_path, monkeypatch):
    p = Pair(tmp_path, monkeypatch)
    yield p
    p.close()


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_new_path_ends_in_identical_rows_and_database_over_random_frames(pair, seed):
    assert run_script(pair, seed, 60) == ""


def test_500_row_frames_match_and_an_unchanged_second_import_takes_no_write_lock(pair):
    rng = random.Random(7)
    rows = [frame_row(i, rng) for i in range(500)]
    old, new = pair.sync(0, rows)
    assert old == new and not pair.differ()
    for row in rows[:25]:
        row["label"] = "changed"
    old, new = pair.sync(0, rows)
    assert old == new and not pair.differ()
    statements: list = []
    pair.conns[1].set_trace_callback(statements.append)
    old, new = pair.sync(0, rows)
    pair.conns[1].set_trace_callback(None)
    assert old == new and not pair.differ()
    assert not any("BEGIN IMMEDIATE" in s for s in statements), statements[:5]
    assert len(statements) <= 12, len(statements)


def test_a_project_move_or_rename_between_two_imports_rebinds_like_the_old_path(pair):
    row = {"session_uuid": "u1", "row_id": 1, "name": "carnivore_n1", "working_dir": "/w/a", "label": "api", "project_uid": UIDS[0]}
    old, new = pair.sync(0, [row])
    assert old == new and not pair.differ()
    pair.both("UPDATE projects SET display_name = 'renamed' WHERE root LIKE 'peer://%'")
    old, new = pair.sync(0, [row])
    assert old == new and old["carnivore_n1"].project_name == "renamed" and not pair.differ()
    pair.both("UPDATE projects SET root = ? WHERE root LIKE 'peer://%'", (f"peer://{pair.keys[0]}/w/moved",))
    old, new = pair.sync(0, [row])
    assert old == new and not pair.differ()
    other = {**row, "session_uuid": "u2", "name": "carnivore_n2", "row_id": 2, "project_uid": None}
    old, new = pair.sync(0, [row, other])
    assert old == new and not pair.differ()


def test_breaking_the_skip_rule_turns_the_differential_red(pair, monkeypatch):
    row = {"session_uuid": "u1", "row_id": 1, "name": "carnivore_n1", "working_dir": "/w/a", "label": "api"}
    assert pair.sync(0, [row])[0] == pair.sync(0, [row])[1] and not pair.differ()
    real = shadow_rows_diff._same
    monkeypatch.setattr(shadow_rows_diff, "_same", lambda a, b: True if isinstance(a, str) and isinstance(b, str) else real(a, b))
    pair.sync(0, [{**row, "label": "other"}])
    assert pair.differ() != ""


def test_the_replan_under_the_write_lock_rechecks_instead_of_trusting_the_snapshot(pair, monkeypatch):
    rows = [{"session_uuid": f"u{i}", "row_id": i, "name": f"carnivore_n{i}", "working_dir": "/w/a", "label": f"api{i}"} for i in (1, 2)]
    pair.sync(0, rows)
    conn = pair.conns[1]
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real = shadow_rows_diff._read_plan

    def racing(c, *args):
        plan = real(c, *args)
        c.execute("UPDATE sessions SET title = 'stale' WHERE origin = 'peer' AND tmux_name = 'carnivore_n2'")
        c.commit()
        return plan

    monkeypatch.setattr(shadow_rows_diff, "_read_plan", racing)
    frame = [{**rows[0], "label": "relabelled"}, rows[1]]
    shadow_rows.sync_peer(conn, host_key=pair.keys[0], peer_install_id=PEERS[0][0], rows=frame, complete=True)
    assert conn.execute("SELECT title FROM sessions WHERE origin = 'peer' AND tmux_name = 'carnivore_n2'").fetchone()[0] == "api2"


def test_two_peer_uuids_on_one_shadow_row_fall_back_to_the_full_sync(pair, monkeypatch):
    rows = [{"session_uuid": f"u{i}", "row_id": i, "name": f"carnivore_n{i}", "working_dir": "/w/a", "label": f"api{i}"} for i in (1, 2)]
    old, new = pair.sync(0, rows)
    assert old == new and not pair.differ()
    pair.both("DELETE FROM peer_sessions WHERE peer_session_uuid = 'u2'")
    pair.both("UPDATE peer_sessions SET session_id = (SELECT id FROM sessions WHERE tmux_name = 'carnivore_n2') WHERE peer_session_uuid = 'u1'")
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    plan = shadow_rows_diff._plan(pair.conns[1], pair.keys[0], PEERS[0][0], rows, True, None, False)
    assert plan.full is True
    outcomes = []
    for on, conn in zip((False, True), pair.conns):
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
        with pytest.raises(sqlite3.IntegrityError) as err:
            shadow_rows.sync_peer(conn, host_key=pair.keys[0], peer_install_id=PEERS[0][0], rows=[dict(r) for r in rows], complete=True, asleep=None)
        outcomes.append(str(err.value))
    assert outcomes[0] == outcomes[1] and not pair.differ()


def test_deleted_peer_project_tombstone_prevents_resurrection_on_both_paths(pair):
    from src.core import project_writes

    live_a = {"session_uuid": "ua-live", "row_id": 1, "name": "carnivore_a_live", "working_dir": "/w/a", "label": "A live"}
    asleep_a = {"session_uuid": "ua-sleep", "row_id": 2, "name": "carnivore_a_sleep", "working_dir": "/w/a", "label": "A sleep", "source": SLEEP}
    asleep_b = {"session_uuid": "ub-sleep", "row_id": 3, "name": "carnivore_b_sleep", "working_dir": "/w/b", "label": "B sleep", "source": SLEEP}

    old, new = pair.sync(0, [live_a], asleep=[asleep_a, asleep_b])
    assert old == new and not pair.differ()

    root_a = shadow_rows.peer_project_root(pair.keys[0], "/w/a")
    for conn in pair.conns:
        pid = conn.execute("SELECT id FROM projects WHERE root = ?", (root_a,)).fetchone()[0]
        project_writes.delete_project(conn, int(pid))

    old2, new2 = pair.sync(0, [live_a], asleep=[asleep_a, asleep_b])
    assert old2 == new2 == {}
    assert not pair.differ()
    for conn in pair.conns:
        assert conn.execute("SELECT 1 FROM projects WHERE root = ?", (root_a,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM sessions WHERE working_dir = '/w/a' AND (lifecycle = 'running' OR lifecycle_source IS NOT NULL)").fetchone() is None
        root_b = shadow_rows.peer_project_root(pair.keys[0], "/w/b")
        assert conn.execute("SELECT 1 FROM projects WHERE root = ?", (root_b,)).fetchone() is not None
        assert conn.execute("SELECT 1 FROM sessions WHERE working_dir = '/w/b' AND lifecycle_source = ?", (SLEEP,)).fetchone() is not None
