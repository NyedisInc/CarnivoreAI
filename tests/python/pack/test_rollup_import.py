from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest
import structlog

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities as caps, config_state, exchange
from src.core.pack.rollup_import import puller, store
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.stats import config as stats_config, rollup
from src.core.stats.plugin import revision, schema
from src.core.stats.plugin import rollup as write
from tests.python.pack.test_machines_roster import FakeCollector

HOUR = 3600
BASE = 1_760_000_000 // HOUR * HOUR
CAPS = ["pack.machine", caps.CAP_PIPELINE_ROLLUP]
PEER = "install-a"


def _stats_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    schema.migrate(conn, 0)
    return conn


def _conversation(conn: sqlite3.Connection, name: str, project: str, hours: List[int], seed: int = 1) -> None:
    row = conn.execute("SELECT id FROM dim_source WHERE conversation_id = ?", (name,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind) VALUES (?,?,?,?)",
                     (abs(hash(name)) % (2 ** 62), name, "claude", "session"))
        row = conn.execute("SELECT id FROM dim_source WHERE conversation_id = ?", (name,)).fetchone()
    rng = random.Random(seed)
    batch = write.Batch(row[0])
    for hour in hours:
        t = BASE + hour * HOUR + 120
        batch.add_usage(t, "claude-opus", project, "v1", (rng.randrange(1, 900), 3, rng.randrange(0, 5000), 7), 1000, 1)
        batch.add_counter(t, "claude-opus", project, "tool_calls", "Bash", rng.randrange(1, 9))
    batch.flush(conn, {})
    conn.commit()


class Peer:

    def __init__(self, tmp: Path) -> None:
        self.conn = _stats_db(tmp / "a-stats.db")
        self.excluded: FrozenSet[str] = frozenset()
        self.requests: List[Dict[str, Any]] = []
        self.status = 200

    def snapshot(self) -> Dict[str, Any]:
        return {"install_id": PEER, "pipeline_rev": {"stats": revision.current(self.conn)}}

    async def post(self, method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
        assert method == "GET" and path.startswith(puller.ROLLUP_PATH + "?")
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        self.requests.append(q)
        page = rollup.export_rollup(
            self.conn, int(q["since_rev"]), until_revision=int(q["until_rev"]) if "until_rev" in q else None,
            cursor=q.get("cursor"), exclude_projects=self.excluded, max_bytes=int(q["max_bytes"]))
        return self.status, json.loads(json.dumps({"available": True, **page}))


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def b_state(tmp_path):
    state = tmp_path / "b"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    with closing(connect(db_path_for(state))) as conn:
        peer_hosts.upsert(conn, install_id=PEER, label="hosta", grant_id="g1", fid="f1", initiator=False)
    return state


def _importer(state: Path, peer: Peer, clock: Clock, capabilities: Optional[List[str]] = None) -> puller.RollupImporter:
    return puller.RollupImporter(lambda: connect(db_path_for(state)), lambda iid: peer.post,
                                 lambda iid: CAPS if capabilities is None else capabilities, clock)


def _totals(state: Path) -> Tuple[int, int, int]:
    with closing(connect(db_path_for(state))) as conn:
        usage = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(input), 0) FROM {USAGE_TABLE} WHERE peer_install_id = ?", (PEER,)).fetchone()
        counters = conn.execute(f"SELECT COUNT(*) FROM {COUNTER_TABLE} WHERE peer_install_id = ?", (PEER,)).fetchone()[0]
    return usage[0], usage[1], counters


def _source_totals(conn: sqlite3.Connection) -> Tuple[int, int, int]:
    usage = conn.execute("SELECT COUNT(*), COALESCE(SUM(i), 0) FROM (SELECT SUM(u.input) i FROM usage_hour u JOIN dim_source s ON s.id = u.src "
                         "GROUP BY s.conversation_id, u.t, u.model, u.project)").fetchone()
    counters = conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM counter_hour c JOIN dim_source s ON s.id = c.src "
                            "GROUP BY s.conversation_id, c.t, c.model, c.project, c.counter, c.key)").fetchone()[0]
    return usage[0], usage[1], counters


def _run(coro):
    return asyncio.run(coro)


def test_a_revision_bump_is_pulled_exactly_once_and_equals_the_source(tmp_path, b_state, monkeypatch):
    monkeypatch.setattr(puller, "PAGE_BYTES", 4096)
    peer, clock = Peer(tmp_path), Clock()
    for i in range(30):
        _conversation(peer.conn, f"conv-{i:03d}", f"proj{i % 3}", list(range(6)), seed=i)
    importer = _importer(b_state, peer, clock)
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    first = list(peer.requests)
    assert len(first) > 1, "the pull must have taken several pages"
    assert first[0]["since_rev"] == "0" and all(r["until_rev"] == first[1]["until_rev"] for r in first[1:])
    stored = _totals(b_state)
    assert stored[0] > 0 and stored == _source_totals(peer.conn), "the union of pages is the source"
    with closing(connect(db_path_for(b_state))) as conn:
        assert store.get_state(conn, PEER).revision == revision.current(peer.conn)
    peer.requests.clear()
    clock.now += 600
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert peer.requests == [], "an unchanged revision pulls nothing"

    _conversation(peer.conn, "conv-005", "proj2", [2, 9], seed=99)
    clock.now += 61
    before = store.get_state(connect(db_path_for(b_state)), PEER).revision
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert len(peer.requests) == 1 and peer.requests[0]["since_rev"] == str(before), "one incremental page, from the stored revision"
    assert _totals(b_state) == _source_totals(peer.conn), "replaced rows, not doubled"


def test_pulls_are_spaced_sixty_seconds_apart(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "c1", "p", [0])
    importer = _importer(b_state, peer, clock)
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    _conversation(peer.conn, "c1", "p", [1])
    peer.requests.clear()
    clock.now += 30
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert peer.requests == [], "inside 60 s the next beat retries, nothing is pulled"
    clock.now += 31
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert len(peer.requests) == 1


def test_the_pulled_revision_survives_a_restart_and_never_moves_backwards(tmp_path, b_state, monkeypatch):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "c1", "p", [0, 1])
    _run(_importer(b_state, peer, clock).maybe_pull(PEER, peer.snapshot()))
    peer.requests.clear()
    clock.now += 500
    _run(_importer(b_state, peer, clock).maybe_pull(PEER, peer.snapshot()))
    assert peer.requests == []
    one = revision.current(peer.conn)
    peer.conn.close()
    reopened = sqlite3.connect(tmp_path / "a-stats.db")
    assert revision.current(reopened) == one

    class Store:
        def connect(self, readonly: bool = False):
            return reopened

    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": True})
    assert rollup.advertised_revisions(Store()) == {"stats": one}
    monkeypatch.setattr(stats_config, "get_settings", lambda s: {"enabled": False})
    assert rollup.advertised_revisions(Store()) == {}, "stats off advertises nothing"
    assert rollup.advertised_revisions(None) == {}


def test_a_peer_without_the_capability_is_skipped_with_one_log_line(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "c1", "p", [0])
    importer = _importer(b_state, peer, clock, capabilities=["pack.machine"])
    with structlog.testing.capture_logs() as logs:
        for _ in range(3):
            clock.now += 100
            _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert peer.requests == [] and _totals(b_state) == (0, 0, 0)
    skipped = [e for e in logs if e["event"] == "pack_rollup_skipped"]
    assert len(skipped) == 1 and skipped[0]["reason"] == "no_capability"


def test_a_peer_that_advertises_no_revision_is_never_called(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _run(_importer(b_state, peer, clock).maybe_pull(PEER, {"install_id": PEER}))
    assert peer.requests == []


def test_a_rebuilt_peer_and_a_changed_exclusion_set_purge_and_repull(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "c1", "keep", [0, 1])
    _conversation(peer.conn, "c2", "gapped", [0, 1])
    importer = _importer(b_state, peer, clock)
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert _totals(b_state)[0] == 4

    peer.excluded = frozenset({"gapped"})
    _conversation(peer.conn, "c1", "keep", [2])
    peer.requests.clear()
    clock.now += 100
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert [r["since_rev"] for r in peer.requests][-1] == "0", "restarted from revision 0"
    with closing(connect(db_path_for(b_state))) as conn:
        assert {r[0] for r in conn.execute(f"SELECT DISTINCT project FROM {USAGE_TABLE}")} == {"keep"}

    with closing(connect(db_path_for(b_state))) as conn:
        conn.execute(f"UPDATE {STATE_TABLE} SET revision = revision + 10000000")
        conn.execute(f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, model, project) VALUES (?, 'ghost', 1, 'm', 'p')", (PEER,))
    clock.now += 100
    _conversation(peer.conn, "c1", "keep", [3])
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    with closing(connect(db_path_for(b_state))) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE conversation_id = 'ghost'").fetchone()[0] == 0
        assert store.get_state(conn, PEER).revision == revision.current(peer.conn)
    assert _totals(b_state)[0] > 0


def test_unpair_purges_the_rollups_and_a_late_page_writes_nothing(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "c1", "p", [0, 1, 2])
    _run(_importer(b_state, peer, clock).maybe_pull(PEER, peer.snapshot()))
    assert _totals(b_state)[0] == 3
    with closing(connect(db_path_for(b_state))) as conn:
        assert peer_hosts.delete(conn, PEER)
        assert store.get_state(conn, PEER) is None
        late = [{"conversation_id": "late", "hour": 1, "usage": [["m", "p", 1, 0, 0, 0, 0, 1, 1]], "counters": []}]
        assert store.apply_page(conn, PEER, late) is None, "an unpaired computer's page is refused"
    assert _totals(b_state) == (0, 0, 0)


def test_malformed_groups_are_skipped_not_half_written(tmp_path, b_state):
    with closing(connect(db_path_for(b_state))) as conn:
        good = {"conversation_id": "ok", "hour": 7, "provider": "claude", "agent_kind": "session",
                "usage": [["m", "p", 1, 2, 3, 4, 5, 6, 7]], "counters": [["m", "p", "tool_calls", "Bash", 2]]}
        bad = [{"conversation_id": "x", "hour": 1, "usage": [["m", "p", "NaN", 0, 0, 0, 0, 0, 0]], "counters": []},
               {"conversation_id": "y", "hour": "1", "usage": [], "counters": []}, "junk", {"hour": 1}]
        assert store.apply_page(conn, PEER, [*bad, good]) == 1
        assert conn.execute(f"SELECT conversation_id FROM {USAGE_TABLE}").fetchall()[0][0] == "ok"
        empty = {"conversation_id": "ok", "hour": 7, "usage": [], "counters": []}
        assert store.apply_page(conn, PEER, [empty]) == 1
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE}").fetchone()[0] == 0


def test_imported_rows_never_reach_the_export(tmp_path, b_state):
    peer, clock = Peer(tmp_path), Clock()
    _conversation(peer.conn, "from-a", "p", [0, 1])
    own = _stats_db(tmp_path / "b-stats.db")
    _conversation(own, "from-b", "q", [0])
    _run(_importer(b_state, peer, clock).maybe_pull(PEER, peer.snapshot()))
    assert _totals(b_state)[0] == 2
    groups = rollup.export_rollup(own, 0)["groups"]
    assert [g["conversation_id"] for g in groups] == ["from-b"], "B exports only what B computed"
    assert own.execute("SELECT COUNT(*) FROM dim_source WHERE conversation_id = 'from-a'").fetchone()[0] == 0


def _machine(tmp_path: Path, name: str, notes: list) -> exchange.PackMachines:
    path = tmp_path / f"{name}.json"
    path.write_text("{}")
    return exchange.PackMachines(
        install_id=f"install-{name}", label=name, app_version="1.0", state=config_state.ConfigState(lambda p=path: p),
        collector=FakeCollector(name), default_master=lambda: "install-a", connected=lambda: [],
        notify=lambda topic, key, every: notes.append((topic, key)))


def test_the_snapshot_carries_the_revision_and_a_beat_hands_it_to_the_importer(tmp_path):
    caps.register(caps.CAP_MACHINE)
    notes: list = []
    a, b = _machine(tmp_path, "a", notes), _machine(tmp_path, "b", notes)
    a.pipeline_rev = lambda: {"stats": 41}
    seen: List[Tuple[str, Any]] = []

    class Spy:
        async def maybe_pull(self, peer_id, snapshot):
            seen.append((peer_id, snapshot.get("pipeline_rev")))

    b.importer = Spy()

    async def post(method, path, body):
        return 200, await a.serve_exchange("install-b", "b", json.loads(json.dumps(body)))

    async def go():
        assert await b.beat("install-a", post, ["pack.machine"])
        await asyncio.gather(*list(b._pull_tasks))

    _run(go())
    assert seen == [("install-a", {"stats": 41})]
    snap = a.own_snapshot()
    a._announce("x", snap, "connected")
    count = len(notes)
    a.pipeline_rev = lambda: {"stats": 42}
    a._announce("x", a.own_snapshot(), "connected")
    assert snap["pipeline_rev"] == {"stats": 41} and len(notes) == count
