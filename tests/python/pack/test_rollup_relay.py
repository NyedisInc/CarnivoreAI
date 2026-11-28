from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities as caps
from src.core.pack.rollup_import import puller, relay_export
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, PROJECTS_TABLE, USAGE_TABLE
from src.core.stats import config as stats_config, rollup
from src.core.stats.plugin import revision
from src.core.stats.plugin.extract import project_key
from tests.python.pack.test_rollup_import import Clock, _conversation, _source_totals, _stats_db

CAPS = ["pack.machine", caps.CAP_PIPELINE_ROLLUP, caps.CAP_ROLLUP_RELAY]


class Node:

    def __init__(self, tmp: Path, name: str) -> None:
        self.name, self.iid = name, f"iid-{name}"
        self.state = tmp / name
        self.state.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.stats_path = tmp / f"{name}-stats.db"
        self.stats = _stats_db(self.stats_path)
        self.clock = Clock()
        self.importer: Optional[puller.RollupImporter] = None
        self.state_dir = self.state

    def open_db(self) -> sqlite3.Connection:
        return connect(db_path_for(self.state))

    def connect(self, readonly: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.stats_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def pair(self, *others: "Node") -> None:
        with closing(self.open_db()) as conn:
            for other in others:
                peer_hosts.upsert(conn, install_id=other.iid, label=other.name, grant_id=f"g-{other.name}", fid=f"f-{other.name}", initiator=False)

    def snapshot(self) -> Dict[str, Any]:
        return {"install_id": self.iid, "pipeline_rev": {"stats": revision.current(self.stats), **relay_export.advertised(self.open_db)}}

    def post_to(self, target: "Node"):
        async def post(method: str, path: str, body: Optional[dict]) -> Tuple[int, Any]:
            assert method == "GET" and path.startswith(puller.ROLLUP_PATH + "?")
            q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
            page = relay_export.serve_stream(
                target, target.open_db, caller=self.iid, stream=q.get("stream"), since_revision=int(q["since_rev"]),
                until_revision=int(q["until_rev"]) if "until_rev" in q else None, cursor=q.get("cursor"), max_bytes=int(q["max_bytes"]))
            return 200, json.loads(json.dumps(page))
        return post

    def pull(self, target: "Node") -> None:
        self.clock.now += 61
        asyncio.run(self.importer.maybe_pull(target.iid, target.snapshot()))


def _held(node: Node, origin: str) -> Tuple[int, int, int]:
    with closing(node.open_db()) as conn:
        usage = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(input), 0) FROM {USAGE_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()
        counters = conn.execute(f"SELECT COUNT(*) FROM {COUNTER_TABLE} WHERE peer_install_id = ?", (origin,)).fetchone()[0]
    return usage[0], usage[1], counters


def test_a_star_relays_every_row_under_its_origin_and_never_echoes(tmp_path, monkeypatch):
    monkeypatch.setattr(stats_config, "get_settings", lambda store: {"enabled": True})
    monkeypatch.setattr(caps, "mesh_on", lambda: False)
    a, b, c = Node(tmp_path, "a"), Node(tmp_path, "b"), Node(tmp_path, "c")
    a.pair(b, c)
    b.pair(a)
    c.pair(a)
    root = str(tmp_path / "carnivore")
    with closing(c.open_db()) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'carnivore', 'manual', 'now', 'now')",
                     (root, root))
    nodes = {n.iid: n for n in (a, b, c)}
    _conversation(a.stats, "conv-a", "a" * 24, [0, 1], seed=1)
    _conversation(b.stats, "conv-b", "b" * 24, [0, 1, 2], seed=2)
    _conversation(c.stats, "conv-c", project_key(root), [0, 1], seed=3)
    for node, peers in ((a, (b, c)), (b, (a,)), (c, (a,))):
        node.importer = puller.RollupImporter(node.open_db, lambda iid, node=node: node.post_to(nodes[iid]), lambda iid: CAPS, node.clock, self_id=node.iid)

    a.pull(b)
    a.pull(c)
    b.pull(a)
    c.pull(a)

    assert _held(b, c.iid) == _source_totals(c.stats) and _held(b, c.iid)[0] > 0, "B holds C's rows under C"
    assert _held(c, b.iid) == _source_totals(b.stats) and _held(c, b.iid)[0] > 0, "C holds B's rows under B"
    assert _held(b, a.iid) == _source_totals(a.stats) and _held(c, a.iid) == _source_totals(a.stats)
    assert _held(a, b.iid) == _source_totals(b.stats) and _held(a, c.iid) == _source_totals(c.stats)
    for node in (a, b, c):
        assert _held(node, node.iid) == (0, 0, 0), "no computer holds a row under its own id"
    with closing(b.open_db()) as conn:
        assert conn.execute(f"SELECT name FROM {PROJECTS_TABLE} WHERE peer_install_id = ? AND project = ?", (c.iid, project_key(root))).fetchone()[0] == "carnivore"
        assert conn.execute("SELECT via, hops FROM pack_rollup_state WHERE peer_install_id = ?", (c.iid,)).fetchone()[:] == (a.iid, 2)

    for caller, other in ((b, c), (c, b)):
        page = relay_export.serve_stream(a, a.open_db, caller=caller.iid, stream="relay", since_revision=0, max_bytes=rollup.PAGE_BYTES)
        assert page["available"] is True and page["stream"] == "relay"
        assert caller.iid not in page["origins"] and other.iid in page["origins"]
        assert page["groups"] and all(g["origin"] != caller.iid for g in page["groups"])

    old = relay_export.serve_stream(a, a.open_db, caller=b.iid, stream=None, since_revision=0, max_bytes=rollup.PAGE_BYTES)
    assert json.dumps(old, sort_keys=True) == json.dumps(rollup.serve(a, since_revision=0, until_revision=None, cursor=None, max_bytes=rollup.PAGE_BYTES), sort_keys=True)
    assert {g["conversation_id"] for g in old["groups"]} == {"conv-a"}
    assert not {"origin", "project_names", "stream", "one_way"} & set(old) and all("origin" not in g for g in old["groups"])

    _conversation(c.stats, "conv-c", project_key(root), [1, 5], seed=9)
    a.pull(c)
    b.pull(a)
    assert _held(b, c.iid) == _source_totals(c.stats)
    assert _held(a, c.iid) == _source_totals(c.stats)
