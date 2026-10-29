
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from src.core.db import db_path_for
from src.core.pipeline import plugin_db, registry, scan
from src.core.pipeline.deliver import FileTarget
from src.core.pipeline.engine import Engine
from src.core.deepsearch import constants as K
from src.core.deepsearch import pipeline_plugin as dp
from src.core.deepsearch import rules as rules_mod
from src.core.deepsearch import search
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.cache import flip
from src.core.deepsearch.live import store
from src.core.deepsearch.live.indexer import FileSpec, index_file
from src.core.transcript_source import scope as scope_mod
from tests.pipeline import corpus as C
from tests.s7_helpers import migrated_connection

CONV_A = "aaaaaaaa-0000-0000-0000-00000000000a"
CONV_B = "bbbbbbbb-0000-0000-0000-00000000000b"
CONV_S = "cccccccc-0000-0000-0000-00000000000c"
CODEX = "rollout-2026-09-01T12-00-00-dddddddd-0000-0000-0000-00000000000d"
GHOSTS = ("toolsecretword", "sdkghostword", "subagentghost")
EXPECTED = {"zebrafoo": 2, "quokkabar": 1, "wombatbaz": 1, "onlyone": 1, "codexneedle": 1}


def line(i: int, text: Any, kind: str = "user", **extra: Any) -> bytes:
    role = "assistant" if kind == "assistant" else "user"
    return (json.dumps({"type": kind, "uuid": f"u-{i}", "message": {"role": role, "content": text}, **extra},
                       sort_keys=True) + "\n").encode()


def tool_result(i: int, text: str) -> bytes:
    return line(i, [{"type": "tool_result", "tool_use_id": f"t{i}", "content": text}])


def _a_lines() -> bytes:
    return (line(0, "zebrafoo planning notes") + line(1, "quokkabar answer about zebrafoo", "assistant")
            + tool_result(2, "toolsecretword in a tool output") + line(3, "the third message mentions wombatbaz"))


def _codex_lines() -> bytes:
    return C.jl({"type": "session_meta", "timestamp": C.stamp(0), "payload": {"cwd": C.PROJECT_CWD}},
                {"type": "event_msg", "timestamp": C.stamp(1), "payload": {"type": "user_message",
                                                                          "message": "codexneedle prompt"}})


@pytest.fixture()
def world(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(rules_mod, "default_config_path", lambda: config)
    monkeypatch.setattr(K, "INDEX_SCOPE", "human")
    monkeypatch.setattr(scan.Scanner, "_walk", lambda self: SimpleNamespace(changed=()))
    states = {}
    for name in ("old", "new"):
        state = tmp_path / name
        state.mkdir()
        migrated_connection(state).close()
        states[name] = state
    folder = (tmp_path / "projects" / C.CLAUDE_FOLDER).resolve()
    (folder / CONV_A / "subagents").mkdir(parents=True)
    files = SimpleNamespace(
        a=folder / f"{CONV_A}.jsonl", b=folder / f"{CONV_B}.jsonl", s=folder / f"{CONV_S}.jsonl",
        sub=folder / CONV_A / "subagents" / "agent-1.jsonl", codex=tmp_path / "codex" / f"{CODEX}.jsonl")
    files.codex.parent.mkdir()
    files.a.write_bytes(_a_lines())
    files.b.write_bytes(line(0, "alpha stage onlyone"))
    files.s.write_bytes(line(0, "headless sdkghostword", entrypoint="sdk-cli"))
    files.sub.write_bytes(line(0, "subagent said subagentghost", "assistant", isSidechain=True))
    files.codex.write_bytes(_codex_lines())
    specs = [(CONV_A, files.a, "conversation", "claude"), (CONV_B, files.b, "conversation", "claude"),
             (CONV_S, files.s, "conversation", "claude"), (CONV_A, files.sub, "subagent", "claude"),
             (CODEX, files.codex, "conversation", "codex")]
    return SimpleNamespace(old=states["old"], new=states["new"], files=files, specs=specs, config=config)


class Driver:

    def __init__(self, state: Path, plugins: Optional[Sequence[Any]] = None) -> None:
        self.state = state
        self.now = 0.0
        self.engine = Engine(state, db_path=db_path_for(state), clock=lambda: self.now, wall=lambda: C.T0,
                             plugins=registry.plugins(plugins if plugins is not None else [dp.DEEPSEARCH]))

    def drain(self) -> None:
        self.now += 10.0
        for _ in range(400):
            delay = self.engine.step()
            if delay is None or delay > 0:
                return
        raise AssertionError("the worker never ran out of due work")

    def mark(self, path: Path, conv: str, family: str = "claude", kind: str = "conversation") -> None:
        self.engine.mark_dirty(FileTarget(str(path), conv, family, kind))

    def deliver(self, specs: Sequence[Tuple[str, Path, str, str]]) -> None:
        for conv, path, kind, family in specs:
            self.mark(path, conv, family, kind)
        self.drain()
        assert self.engine.status()["plugins"]["deepsearch"]["failures"] == 0, self.engine.status()


def old_index(state: Path, specs: Sequence[Tuple[str, Path, str, str]], overrides: Optional[Dict[str, Any]] = None) -> None:
    with closing(cache_db.open_cache(state)) as conn:
        for conv, path, kind, family in specs:
            if kind == "subagent" and not scope_mod.includes_subagents(K.INDEX_SCOPE):
                continue
            index_file(conn, FileSpec(conv, str(path), kind, family), overrides=overrides, scope=K.INDEX_SCOPE)


def hits(state: Path, query: str, overrides: Optional[Dict[str, Any]] = None) -> List[tuple]:
    with closing(cache_db.reader(state)) as conn:
        found = search.search(conn, state, query, overrides=overrides if overrides is not None else {})["hits"]
    return sorted((h["conversation_id"], h["line"], h["kind"], h["frame_offset"], h["snippet"]) for h in found)


def live_rows(state: Path) -> Dict[str, Tuple[int, int, int, int]]:
    with closing(sqlite3.connect(f"file:{state / K.CACHE_FILENAME}?mode=ro", uri=True)) as conn:
        return {r[0]: tuple(r[1:]) for r in conn.execute(
            f"SELECT path, indexed_offset, indexed_lines, rows, in_scope FROM {K.LIVE_TABLE}")}


def test_the_plugin_is_registered_and_keeps_its_file_beside_the_database(world):
    ids = [p.id for p in registry.plugins()]
    assert ids == ["stats", "deepsearch"]
    assert plugin_db.db_path(world.new, dp.DEEPSEARCH) == world.new / "deepsearch.db"
    assert plugin_db.db_path(world.new, registry.find("stats")) == world.new / "pipeline-plugins" / "stats.db"


def test_the_same_corpus_gives_the_same_non_empty_hits_as_the_old_index(world):
    f = world.files
    for word in GHOSTS:
        assert any(word.encode() in p.read_bytes() for p in (f.a, f.s, f.sub))
    old_index(world.old, world.specs)
    Driver(world.new).deliver(world.specs)
    total = 0
    for word, count in EXPECTED.items():
        old, new = hits(world.old, word), hits(world.new, word)
        assert len(old) == count and new == old, (word, old, new)
        total += len(new)
    assert total == sum(EXPECTED.values()) == 6
    for word in GHOSTS:
        assert hits(world.old, word) == hits(world.new, word) == []
    old_rows, new_rows = live_rows(world.old), live_rows(world.new)
    assert new_rows == old_rows and str(f.sub) not in new_rows and new_rows[str(f.s)][3] == 0
    assert len(new_rows) == 4


def test_lines_appended_later_are_indexed_from_where_the_cursor_stood(world):
    f = world.files
    driver = Driver(world.new)
    driver.deliver([world.specs[1]])
    assert [h[2] for h in hits(world.new, "onlyone")] == ["user"] and hits(world.new, "lateword") == []
    with open(f.b, "ab") as handle:
        handle.write(line(1, "later stage lateword", "assistant"))
    driver.deliver([world.specs[1]])
    old_index(world.old, [world.specs[1]])
    for word in ("onlyone", "lateword"):
        assert len(hits(world.new, word)) == 1 and hits(world.new, word) == hits(world.old, word)
    assert live_rows(world.new) == live_rows(world.old) == {str(f.b): (f.b.stat().st_size, 2, 2, 1)}


def test_a_live_row_deleted_by_a_purge_or_a_move_is_read_back_from_the_index_end(world):
    f = world.files
    driver = Driver(world.new)
    driver.deliver([world.specs[0]])
    assert len(hits(world.new, "zebrafoo")) == 2
    with closing(cache_db.open_cache(world.new)) as conn:
        live = store.get(conn, str(f.a))
        store.delete_file(conn, int(live.id))
    assert hits(world.new, "zebrafoo") == []
    with open(f.a, "ab") as handle:
        handle.write(line(4, "after the move: newcomer", "assistant"))
    driver.deliver([world.specs[0]])
    old_index(world.old, [world.specs[0]])
    for word in ("zebrafoo", "wombatbaz", "newcomer"):
        assert hits(world.new, word) == hits(world.old, word) and len(hits(world.new, word)) >= 1, word


def test_changed_filter_rules_re_read_the_file_whole_on_its_next_delivery(world):
    f = world.files
    driver = Driver(world.new)
    driver.deliver([world.specs[0]])
    assert hits(world.new, "toolsecretword") == []
    rules = {"blocks": {"tool_result": "keep"}}
    world.config.write_text(json.dumps({"save_pipeline": {"search_filter": rules}}))
    with open(f.a, "ab") as handle:
        handle.write(line(4, "a line after the rules changed", "assistant"))
    driver.deliver([world.specs[0]])
    old_index(world.old, [world.specs[0]], overrides=rules)
    found = hits(world.new, "toolsecretword", overrides=rules)
    assert len(found) == 1 and found == hits(world.old, "toolsecretword", overrides=rules)
    assert live_rows(world.new) == live_rows(world.old)


def test_a_rewritten_file_forgets_what_it_held_and_a_removed_file_leaves_nothing(world):
    f = world.files
    driver = Driver(world.new)
    driver.deliver([world.specs[0], world.specs[3]])
    assert len(hits(world.new, "zebrafoo")) == 2
    f.a.write_bytes(line(0, "compaction rewrote this: pangolinword") + line(1, "second", "assistant"))
    driver.mark(f.a, CONV_A)
    driver.drain()
    assert hits(world.new, "zebrafoo") == [] and len(hits(world.new, "pangolinword")) == 1
    f.a.unlink()
    driver.engine.mark_file_removed(FileTarget(str(f.a), CONV_A, "claude", "conversation"))
    driver.drain()
    assert hits(world.new, "pangolinword") == [] and live_rows(world.new) == {}
    assert driver.engine.status()["plugins"]["deepsearch"]["failures"] == 0


def test_an_index_the_old_engine_built_is_started_over_exactly_once_and_the_cache_reads_building_until_caught_up(
        world, monkeypatch):
    calls: List[bool] = []
    real = dp._start_over
    monkeypatch.setattr(dp, "_start_over", lambda conn: calls.append(real(conn)) or calls[-1])
    old_index(world.new, world.specs)
    flip.mark_ready(world.new)
    assert len(hits(world.new, "zebrafoo")) == 2 and flip.state(world.new) == K.CACHE_READY
    assert calls == []
    first = Driver(world.new)
    first.engine.scanner.run_once()
    for conv, path, kind, family in world.specs:
        first.mark(path, conv, family, kind)
    assert first.engine.signal_caught_up() is False
    first.drain()
    assert calls == [True]
    assert len(hits(world.new, "zebrafoo")) == 2 and flip.state(world.new) == K.CACHE_READY
    assert first.engine.status()["plugins"]["deepsearch"]["failures"] == 0
    second = Driver(world.new)
    second.mark(world.files.a, CONV_A)
    second.drain()
    assert calls == [True] and len(hits(world.new, "zebrafoo")) == 2


def test_building_is_what_a_peer_and_the_local_search_see_until_the_engine_has_delivered_everything(world):
    assert flip.state(world.new) == K.CACHE_BUILDING
    driver = Driver(world.new)
    driver.engine.scanner.run_once()
    assert driver.engine.scanner.last["status"] == "ok"
    driver.mark(world.files.a, CONV_A)
    driver.mark(world.files.b, CONV_B)
    assert driver.engine.signal_caught_up() is False and flip.state(world.new) == K.CACHE_BUILDING
    driver.drain()
    assert flip.state(world.new) == K.CACHE_READY and flip.info(world.new)["built_at"] is not None
    assert driver.engine.signal_caught_up() is True
    out = driver.engine.rebuild_plugin("deepsearch")
    assert out["plugin"] == "deepsearch" and out["files_marked"] == 0
    assert flip.state(world.new) == K.CACHE_BUILDING and hits(world.new, "zebrafoo") == []
