
from __future__ import annotations

import json
import time
from contextlib import closing
from pathlib import Path

import pytest

from tests.python.deepsearch.helpers import build_world, drain, go_ready, rec, scan, teardown
from tests.python.transcript_source.helpers import CONV, FOLDER
from tests.stats.test_rollup_export import _flush, _fresh, _source  # noqa: F401

import random

from src.core.db import connect
from src.core.deepsearch import grouped, peer_air_gap
from src.core.deepsearch.cache import db as cache_db
from src.core.stats import config, project_groups, rollup
from src.core.stats.plugin.extract import project_key
from src.core.stats.store import StatsStore

WORD = "zebrafoo"
MID, OPEN, GROW, NESTED, SUBOK, URI = (f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 7))


def _line(i: int, text: str, cwd: str) -> bytes:
    return rec(i, text, cwd=cwd)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    secret, open_dir = tmp_path / "work" / "secret", tmp_path / "work" / "open"
    for d in (secret / "deep", secret / "nested", open_dir / "sub"):
        d.mkdir(parents=True)
    folder = built["corpus"] / FOLDER
    pad = "x" * 280
    mid = [_line(i, f"{WORD} open work {i} {pad}", str(open_dir / "sub")) for i in range(250)]
    mid.append(_line(250, f"{WORD} the middle of the conversation ran in the secret folder", str(secret / "deep")))
    mid += [_line(251 + i, f"{WORD} open again {i} {pad}", str(open_dir / "sub")) for i in range(400)]
    (folder / f"{MID}.jsonl").write_bytes(b"".join(mid))
    (folder / f"{OPEN}.jsonl").write_bytes(_line(1, f"{WORD} open work", str(open_dir / "sub")))
    (folder / f"{GROW}.jsonl").write_bytes(_line(2, f"{WORD} grows later", str(open_dir / "sub")))
    (folder / f"{NESTED}.jsonl").write_bytes(_line(3, f"{WORD} nested project work", str(secret / "nested")))
    (folder / f"{URI}.jsonl").write_bytes(rec(6, f"{WORD} a tool result with a nested cwd key", cwd=str(open_dir / "sub"),
                                              toolUseResult={"cwd": "file:///Users/someone/proj"}))
    built["main"].write_bytes(_line(0, f"{WORD} main of the conversation with unprovable subagents", str(open_dir / "sub")))
    (folder / SUBOK / "subagents").mkdir(parents=True)
    (folder / f"{SUBOK}.jsonl").write_bytes(_line(4, f"{WORD} main with a provable subagent", str(open_dir / "sub")))
    (folder / SUBOK / "subagents" / "agent-0.jsonl").write_bytes(_line(5, "subagent work", str(open_dir / "sub")))
    with closing(connect(built["db"], create=False)) as conn:
        conn.executemany("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, air_gap) "
                         "VALUES (?, ?, ?, 'user', 't', 't', ?)",
                         [(str(secret), str(secret), "secret", 1), (str(secret / "nested"), str(secret / "nested"), "nested", 0)])
        conn.commit()
    scan(built)
    drain(built)
    go_ready(built)
    built.update(secret=secret, open=open_dir, folder=folder)
    yield built
    teardown()


def _search(world, gate, **kw):
    with closing(cache_db.reader(world["state"])) as conn:
        return grouped.search_grouped(conn, world["state"], WORD, overrides={}, peer_gate=gate, **kw)


def _ids(answer) -> set:
    return {g["conversation_id"] for g in answer["groups"]}


def test_a_folder_recorded_only_mid_file_or_past_the_index_or_in_an_unprovable_subagent_withholds_the_conversation(world):
    everything = {MID, OPEN, GROW, NESTED, SUBOK, URI, CONV}
    owner = _search(world, None, limit=50)
    assert _ids(owner) == everything
    mid_size = (world["folder"] / f"{MID}.jsonl").stat().st_size
    assert mid_size > 120_000
    gate = peer_air_gap.load_gate(world["state"])
    assert gate.active

    peer = _search(world, gate, limit=50)
    assert _ids(peer) == {OPEN, GROW, SUBOK, URI}
    text = json.dumps(peer)
    assert "middle of the conversation" not in text and "nested project work" not in text and "unprovable subagents" not in text
    assert peer["total_conversations"] == 4

    with (world["folder"] / f"{GROW}.jsonl").open("ab") as handle:
        handle.write(_line(9, "grown into the secret folder, not yet indexed", str(world["secret"] / "deep")))
    assert _ids(_search(world, gate, limit=50)) == {OPEN, SUBOK, URI}
    with (world["folder"] / f"{OPEN}.jsonl").open("ab") as handle:
        handle.write(b"\n" * ((8 << 20) + 10))
    assert _ids(_search(world, gate, limit=50)) == {SUBOK, URI}


def test_the_gate_stays_fast_and_a_request_past_its_deadline_withholds(world, monkeypatch):
    gate = peer_air_gap.load_gate(world["state"])
    started = time.monotonic()
    assert len(_ids(_search(world, gate, limit=50))) == 4
    assert time.monotonic() - started < 2.0
    monkeypatch.setattr(peer_air_gap, "READ_BUDGET_SECONDS", -1.0)
    assert _ids(_search(world, gate, limit=50)) == set()


def _stats(world, keys: dict) -> StatsStore:
    store = StatsStore(world["state"])
    store.initialize()
    config.ensure_schema(store)
    config.update_settings(store, enabled=True, revision=config.get_settings(store)["revision"])
    rng = random.Random(5)
    with store.connect() as conn:
        for conv, key in keys.items():
            _flush(conn, _source(conn, conv), key, [0, 1], rng)
        conn.commit()
    return store


def test_the_rollup_exports_only_keys_proven_outside_an_air_gapped_folder(world):
    open_key = project_key(str(world["open"] / "sub"))
    secret_key = project_key(str(world["secret"] / "deep"))
    nested_key = project_key(str(world["secret"] / "nested"))
    orphan_key = project_key(str(world["open"].parent / "nobody-recorded-this"))
    store = _stats(world, {"c-open": open_key, "c-secret": secret_key, "c-nested": nested_key, "c-orphan": orphan_key})
    page = dict(since_revision=0, until_revision=None, cursor=None, max_bytes=rollup.PAGE_BYTES)

    def sent() -> tuple:
        project_groups.forget()
        rollup.forget_index()
        served = rollup.serve(store, **page)
        assert served["available"] is True
        return {g["conversation_id"] for g in served["groups"]}, served["scope_digest"]

    got, digest = sent()
    assert got == {"c-open"}
    with closing(connect(world["db"], create=False)) as conn:
        conn.execute("UPDATE projects SET air_gap = 0")
        conn.commit()
    everything, open_digest = sent()
    assert everything == {"c-open", "c-secret", "c-nested", "c-orphan"}
    assert digest != open_digest
    with closing(connect(world["db"], create=False)) as conn:
        conn.execute("UPDATE projects SET air_gap = 1 WHERE display_name = 'secret'")
        conn.commit()
    again, again_digest = sent()
    assert again == {"c-open"} and again_digest == digest
