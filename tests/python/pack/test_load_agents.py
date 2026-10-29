
from __future__ import annotations

import json
import sqlite3

from src.core.pack.load import agents, process_tree
from src.core.pack.load.process_tree import Proc

PS = """
  100     1  0.5   1024
  101   100  0.0   2048
  102   101 40.0 204800
  103   102 10.5 102400
  200     1  0.0   1024
  201   200  5.0  51200
  300     1 20.0 512000
"""


def test_each_pane_tree_is_summed_once_and_totals_add_up() -> None:
    procs = process_tree.parse(PS)
    rows = [{"session_id": 1, "session_uuid": "u1", "agent_id": 7, "name": "alpha", "pids": [100]},
            {"session_id": 2, "session_uuid": "u2", "agent_id": None, "name": "plain", "pids": [200]},
            {"session_id": 3, "session_uuid": "u3", "agent_id": None, "name": "gone", "pids": []}]
    out = agents.summarise([r for r in rows if r["pids"]], procs)
    first, second = out["rows"]
    assert (first["session_id"], first["cpu_pct"], first["rss_mb"]) == (1, 51.0, 303.0)
    assert (second["session_id"], second["cpu_pct"], second["rss_mb"]) == (2, 5.0, 51.0)
    assert out["carnivore"] == {"cpu_pct": 56.0, "rss_mb": 354.0, "agents": 2}
    assert out["machine"]["cpu_pct"] == 76.0
    assert out["carnivore"]["cpu_pct"] == sum(r["cpu_pct"] for r in out["rows"])


def test_collect_reads_local_running_rows_one_ps_pass_and_stays_under_the_snapshot_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agents, "tmux_argv_prefix", lambda socket: ["/picked/tmux", "-L", socket])
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript("""CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT, tmux_socket TEXT, tmux_name TEXT,
        host_key TEXT, lifecycle TEXT);
        CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, display_name TEXT, session_row_id INTEGER);""")
    conn.execute("INSERT INTO sessions VALUES (1, 'u1', 'cloude', 'carnivore_a', 'local', 'running')")
    conn.execute("INSERT INTO sessions VALUES (2, 'u2', 'cloude', 'carnivore_b', 'peer-x', 'running')")
    conn.execute("INSERT INTO sessions VALUES (3, 'u3', 'cloude', 'carnivore_c', 'local', 'stopped')")
    conn.execute("INSERT INTO swarm_agents VALUES (7, 'Alpha', 1)")
    conn.commit()
    conn.close()
    open_db = lambda: sqlite3.connect(tmp_path / "t.db")  # noqa: E731
    calls = []
    argvs = []
    out = agents.collect(open_db, ps=lambda: calls.append(1) or process_tree.parse(PS),
                         run=lambda argv: argvs.append(argv) or "carnivore_a\t100\ncarnivore_b\t200\n")
    assert argvs[0][:3] == ["/picked/tmux", "-L", "cloude"], "the Pack read uses the version-matching picker"
    assert [r["name"] for r in out["rows"]] == ["Alpha"] and out["rows"][0]["agent_id"] == 7 and len(calls) == 1
    assert agents.collect(open_db, ps=lambda: None, run=lambda argv: "") is None
    many = [{"session_id": i, "session_uuid": "u" * 36, "agent_id": i, "name": "n" * 40, "pids": [1000 + i]} for i in range(400)]
    table = [Proc(1000 + i, 1, 1.0, 1024) for i in range(400)]
    big = agents.summarise(many, table)
    assert len(json.dumps(big)) < 9 * 1024 and big["truncated"] == 400 - len(big["rows"]) and big["count"] == 400
