
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from tests.pipeline.test_r4_air_gap import WORD, _line  # noqa: F401
from tests.python.deepsearch.helpers import build_world, drain, go_ready, scan, teardown
from tests.python.pack.test_rollup_import import PEER, Clock, Peer, _conversation, _importer, _run, b_state  # noqa: F401
from tests.python.transcript_source.helpers import FOLDER
from tests.stats.test_rollup_export import _flush, _source

import random

from src.core.db import connect, db_path_for
from src.core.deepsearch import constants as K, grouped, peer_air_gap, transcript_folders
from src.core.deepsearch.cache import db as cache_db
from src.core.pack.rollup_import import puller
from src.core.pipeline import reader
from src.core.stats import config, project_groups, rollup
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore

OPEN_CONV = "00000011-aaaa-bbbb-cccc-1234567890ab"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    secret, open_dir = tmp_path / "work" / "secret", tmp_path / "work" / "open"
    for d in (secret, open_dir):
        d.mkdir(parents=True)
    folder = built["corpus"] / FOLDER
    (folder / f"{OPEN_CONV}.jsonl").write_bytes(_line(1, f"{WORD} open work", str(open_dir)))
    built["main"].write_bytes(_line(0, f"{WORD} main of the shipped conversation", str(open_dir)))
    with closing(connect(built["db"], create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, air_gap) "
                     "VALUES (?, ?, 'secret', 'user', 't', 't', 1)", (str(secret), str(secret)))
        conn.commit()
    scan(built)
    drain(built)
    go_ready(built)
    yield built
    teardown()


def _search(world, gate):
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], WORD, overrides={}, peer_gate=gate, limit=50)


def test_the_gate_and_the_hit_fetch_read_one_snapshot(world, monkeypatch):
    gate = peer_air_gap.load_gate(world["state"])
    assert gate.active
    before = _search(world, gate)
    opened = {g["conversation_id"]: g for g in before["groups"]}
    assert OPEN_CONV in opened and opened[OPEN_CONV]["hits"], "population: the open conversation answers with hits"

    original = peer_air_gap.PeerGate.admitted

    def admitted_then_a_write(self, conn, meta):
        answer = original(self, conn, meta)
        with closing(cache_db.open_cache(world["state"])) as writer:
            writer.execute(f"DELETE FROM {K.ROWS_TABLE}")
        return answer

    monkeypatch.setattr(peer_air_gap.PeerGate, "admitted", admitted_then_a_write)
    during = _search(world, gate)
    assert [g["conversation_id"] for g in during["groups"]] == [g["conversation_id"] for g in before["groups"]]
    assert all(g["hits"] for g in during["groups"]), "the hit fetch read the gate's snapshot, not the later commit"
    with closing(cache_db.reader(world["state"])) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {K.ROWS_TABLE}").fetchone()[0] == 0


def test_the_gates_tail_read_never_shares_the_engines_read_key(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b'{"cwd": "/a"}\n')
    covered = path.stat().st_size
    with path.open("ab") as handle:
        handle.write(b'{"cwd": "/b/new"}\n')
    release = threading.Event()
    with pytest.raises(reader.ReadTimeout):
        reader.timed(release.wait, 30, timeout=0.05, key=str(path))
    try:
        assert reader.hung_helpers() >= 1
        assert transcript_folders.tail_folders(str(path), covered) == ("/b/new",)
    finally:
        release.set()
    path.write_bytes(path.read_bytes() + b'{"cwd": "/c"}\n')
    gate_release = threading.Event()
    with pytest.raises(reader.ReadTimeout):
        reader.timed(gate_release.wait, 30, timeout=0.05, key=transcript_folders.GATE_KEY_PREFIX + str(path))
    try:
        assert reader.timed(lambda: "read", timeout=1.0, key=str(path)) == "read"
    finally:
        gate_release.set()


def _registry(state_dir: Path, sessions: list, gapped: tuple = ("/work/secret",)) -> None:
    with sqlite3.connect(db_path_for(state_dir)) as db:
        db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, root TEXT, raw_path TEXT, display_name TEXT, "
                   "archived_at TEXT, air_gap INTEGER NOT NULL DEFAULT 0)")
        rows = [(root, 1) for root in gapped] + [("/work/open", 0)]
        db.executemany("INSERT INTO projects (root, raw_path, display_name, air_gap) VALUES (?, ?, ?, ?)",
                       [(root, root, root.rsplit("/", 1)[-1], flag) for root, flag in rows])
        db.execute("CREATE TABLE sessions (working_dir TEXT)")
        db.executemany("INSERT INTO sessions VALUES (?)", [(s,) for s in sessions])


def _serve(store: StatsStore, since: int) -> dict:
    project_groups.forget()
    rollup.forget_index()
    served = rollup.serve(store, since_revision=since, until_revision=None, cursor=None, max_bytes=rollup.PAGE_BYTES)
    assert served["available"] is True
    return served


def test_a_key_not_yet_proven_never_moves_the_digest_and_is_re_sent_by_revision_once_proven(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    _registry(tmp_path, ["/work/secret/web", "/work/open/web"])
    rng = random.Random(3)
    with store.connect() as conn:
        _flush(conn, _source(conn, "c-open"), project_key("/work/open/web"), [0, 1], rng)
        _flush(conn, _source(conn, "c-secret"), project_key("/work/secret/web"), [0, 1], rng)
        conn.commit()
    first = _serve(store, 0)
    digest = first["scope_digest"]
    assert {g["conversation_id"] for g in first["groups"]} == {"c-open"}

    with store.connect() as conn:
        _flush(conn, _source(conn, "c-new"), project_key("/work/open/new"), [0, 1], rng)
        conn.commit()
    unproven = _serve(store, first["revision"])
    assert unproven["groups"] == [] and unproven["scope_digest"] == digest

    with sqlite3.connect(db_path_for(tmp_path)) as db:
        db.execute("INSERT INTO sessions VALUES ('/work/open/new')")
    proven = _serve(store, unproven["revision"])
    assert proven["scope_digest"] == digest and proven["reset"] is False
    assert {g["conversation_id"] for g in proven["groups"]} == {"c-new"}
    assert _serve(store, proven["revision"])["groups"] == []

    with sqlite3.connect(db_path_for(tmp_path)) as db:
        db.execute("UPDATE projects SET air_gap = 1 WHERE display_name = 'open'")
    assert _serve(store, proven["revision"])["scope_digest"] != digest


def test_the_importer_keeps_the_digest_the_pull_started_from(tmp_path, b_state, monkeypatch):
    monkeypatch.setattr(puller, "PAGE_BYTES", 4096)
    peer, clock = Peer(tmp_path), Clock()
    for i in range(40):
        _conversation(peer.conn, f"conv-{i:03d}", f"proj{i % 2}", list(range(6)), seed=i)
    importer = _importer(b_state, peer, clock)
    original = peer.post
    calls = {"n": 0}

    async def post(method, path, body):
        calls["n"] += 1
        if calls["n"] == 2:
            peer.excluded = frozenset({"proj0"})
        return await original(method, path, body)

    importer = puller.RollupImporter(lambda: connect(db_path_for(b_state)), lambda iid: post,
                                     lambda iid: ["pack.machine", puller.caps_mod.CAP_PIPELINE_ROLLUP], clock)
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert calls["n"] > 2, "the pull took several pages"

    def held() -> int:
        with closing(connect(db_path_for(b_state))) as conn:
            return conn.execute("SELECT COUNT(*) FROM pack_rollups WHERE peer_install_id = ? AND project = 'proj0'", (PEER,)).fetchone()[0]

    assert held() > 0, "population: proj0 rows from the early pages are on this computer"
    _conversation(peer.conn, "conv-new", "proj1", [0])
    clock.now += 61
    _run(importer.maybe_pull(PEER, peer.snapshot()))
    assert held() == 0, "the digest change during the first pull is seen on the next one: proj0 is purged"
