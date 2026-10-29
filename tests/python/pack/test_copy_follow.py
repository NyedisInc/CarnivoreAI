
import sqlite3
import subprocess

import pytest

from src.api import pack_copy_sync
from src.core.pack.move import ddl
from src.core.pack.send import follow

SENDER = "iid-a"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


@pytest.fixture
def pair(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    git(a, "init", "-q", "-b", "main")
    commit(a, "one")
    subprocess.run(["git", "clone", "-q", str(a), str(b)], check=True)
    commit(a, "two")
    commit(a, "three")
    git(b, "fetch", "-q", str(a), f"+refs/heads/*:refs/carnivore/{SENDER}/heads/*")
    return a, b


def test_idle_clean_behind_fast_forwards(pair):
    a, b = pair
    assert follow.fast_forward(str(b), SENDER, busy=False) == "fast_forwarded"
    assert git(b, "rev-parse", "HEAD") == git(a, "rev-parse", "HEAD")
    assert follow.fast_forward(str(b), SENDER, busy=False) == "up_to_date"


def test_busy_is_untouched(pair):
    _a, b = pair
    before = git(b, "rev-parse", "HEAD")
    assert follow.fast_forward(str(b), SENDER, busy=True) == "busy"
    assert git(b, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("dirt", ["untracked", "unstaged", "staged"])
def test_dirty_is_untouched(pair, dirt):
    _a, b = pair
    before = git(b, "rev-parse", "HEAD")
    if dirt == "untracked":
        (b / "new.txt").write_text("x")
    else:
        (b / "one").write_text("changed")
        if dirt == "staged":
            git(b, "add", "one")
    assert follow.fast_forward(str(b), SENDER, busy=False) == "dirty"
    assert git(b, "rev-parse", "HEAD") == before


def test_diverged_is_untouched(pair):
    _a, b = pair
    commit(b, "mine")
    before = git(b, "rev-parse", "HEAD")
    assert follow.fast_forward(str(b), SENDER, busy=False) == "diverged"
    assert git(b, "rev-parse", "HEAD") == before


def test_no_incoming_ref_is_a_noop(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "one")
    assert follow.fast_forward(str(repo), SENDER, busy=False) == "no_incoming"


def test_pairing_queries_cover_both_sides_and_end_on_archive():
    conn = sqlite3.connect(":memory:")
    ddl.apply_pack_move(conn)
    conn.execute("CREATE TABLE sessions (session_uuid TEXT, archived_at TEXT, project_id INTEGER)")
    conn.executemany("INSERT INTO sessions VALUES (?, ?, 7)", [("orig", None), ("copy", None), ("gone", "2026-01-01")])
    rows = [("o1", "source", "orig", "iid-a", "iid-b", "moved", '{"mode": "copy"}'), ("o1", "target", "copy", "iid-a", "iid-b", "moved", '{"mode": "copy"}'),
            ("o2", "source", "gone", "iid-a", "iid-b", "moved", '{"mode": "copy"}'), ("o3", "source", "orig", "iid-a", "iid-c", "moved", '{"mode": "move"}')]
    conn.executemany("INSERT INTO pack_session_moves (id, role, session_uuid, source_install_id, target_install_id, state, detail_json, started_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, 't')", rows)
    assert pack_copy_sync.peers_of(conn, "orig") == ["iid-b"]
    assert pack_copy_sync.peers_of(conn, "copy") == ["iid-a"]
    assert pack_copy_sync.peers_of(conn, "gone") == []
    assert pack_copy_sync.paired_in(conn, "iid-b", 7) == ["orig"]
    assert pack_copy_sync.paired_in(conn, "iid-a", 7) == ["copy"]
