
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from unittest import mock
from typing import Any, Dict, List, Tuple

import pytest

from src.core import transcript_corpus_discover as D
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pipeline import scan as pipeline_scan
from src.core.stats import discovery_shared as shared
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest import refresh as refresh_mod
from src.core.transcript_manifest import store

NOW = "2026-11-18T12:00:00.000000+00:00"
LATER = "2026-11-19T12:00:00.000000+00:00"
A, B, C, E = ("aaaaaaaa-0000-0000-0000-00000000000a", "aaaaaaaa-0000-0000-0000-00000000000b",
              "aaaaaaaa-0000-0000-0000-00000000000c", "aaaaaaaa-0000-0000-0000-00000000000e")


def _line(serial: str) -> bytes:
    return json.dumps({"type": "user", "uuid": serial}).encode() + b"\n"


OLD = time.time() - 3600


def _age(*paths: Path) -> None:
    for path in paths:
        os.utime(path, (OLD, OLD))


def _age_tree(root: Path) -> None:
    dirs = [p for p in root.rglob("*") if p.is_dir()] + [root]
    _age(*sorted(dirs, key=lambda p: len(p.parts), reverse=True))


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shared, "_DIR_LISTINGS", D.DirListingCache())
    monkeypatch.setattr(shared, "_CACHE", {})
    monkeypatch.setattr(refresh_mod, "utc_now", lambda: NOW)
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    corpus = tmp_path / "projects"
    slug = corpus / "-Users-x-proj"
    (slug / A / "subagents").mkdir(parents=True)
    (slug / f"{A}.jsonl").write_bytes(_line("a1") + _line("a2"))
    (slug / f"{B}.jsonl").write_bytes(_line("b1") + _line("b2"))
    (slug / f"{C}.jsonl").write_bytes(_line("c1"))
    (slug / A / "subagents" / "agent-1.jsonl").write_bytes(_line("s1"))
    (slug / A / "subagents" / "note.txt").write_text("x")
    return {"db": db_path_for(state), "corpus": corpus, "slug": slug, "tmp": tmp_path}


def _pass(world: Dict[str, Any], db: Path = None):
    return refresh_mod.refresh(db or world["db"], claude_roots=(world["corpus"],), codex_home="")


def _rows(db: Path) -> List[Tuple]:
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(f"SELECT * FROM {K.TABLE} ORDER BY id").fetchall()


def _identity(db: Path, serial: str) -> Tuple[Any, Any]:
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute(f"SELECT id, first_seen FROM {K.TABLE} WHERE path LIKE ?", (f"%{serial}.jsonl",)).fetchone()
    return tuple(row) if row else None


def _shape(result: Any) -> Dict[str, Any]:
    return {"summary": result.summary(), "changed": [vars(r) for r in result.changed],
            "present": [r.path for r in result.present], "removed": [r.path for r in result.removed]}


def _cold(world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    copy = world["tmp"] / "cold.db"
    for suffix in ("", "-wal", "-shm"):
        if Path(f"{world['db']}{suffix}").exists():
            shutil.copy(f"{world['db']}{suffix}", f"{copy}{suffix}")
    warm = (shared._DIR_LISTINGS, shared._CACHE)
    monkeypatch.setattr(shared, "_DIR_LISTINGS", D.DirListingCache())
    monkeypatch.setattr(shared, "_CACHE", {})
    new_loader = store.load_scan_rows
    monkeypatch.setattr(store, "load_scan_rows", lambda conn, listed: store.load_rows(conn))
    try:
        result = _pass(world, copy)
    finally:
        monkeypatch.setattr(store, "load_scan_rows", new_loader)
        monkeypatch.setattr(shared, "_DIR_LISTINGS", warm[0])
        monkeypatch.setattr(shared, "_CACHE", warm[1])
    return {"shape": _shape(result), "rows": _rows(copy),
            "record": pipeline_scan.Scanner(world["tmp"], copy, (), lambda *a: True, lambda *a: True,
                                            refresh_fn=lambda: result).run_once()}


def _warm(world: Dict[str, Any]) -> Dict[str, Any]:
    listed: List[str] = []
    real = os.scandir
    with mock.patch.object(D.os, "scandir", lambda p: listed.append(str(p)) or real(p)):
        result = _pass(world)
    world["listed"] = listed
    return {"shape": _shape(result), "rows": _rows(world["db"]),
            "record": pipeline_scan.Scanner(world["tmp"], world["db"], (), lambda *a: True, lambda *a: True,
                                            refresh_fn=lambda: result).run_once()}


def _same(world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    cold = _cold(world, monkeypatch)
    warm = _warm(world)
    cold["record"].pop("at"), warm["record"].pop("at")
    assert warm == cold
    return warm


def _prime(world: Dict[str, Any]) -> None:
    _pass(world)
    _age_tree(world["corpus"])
    _pass(world)


def test_warm_pass_equals_cold_pass_after_every_change(world, monkeypatch) -> None:
    slug, corpus = world["slug"], world["corpus"]
    _prime(world)

    assert _same(world, monkeypatch)["shape"]["summary"]["unchanged"] == 4
    assert world["listed"] == [], "the warm pass ran on a cache hit: no directory was listed"
    _age_tree(corpus)

    with open(slug / f"{A}.jsonl", "ab") as handle:
        handle.write(_line("a3"))
    assert _same(world, monkeypatch)["shape"]["summary"]["grown"] == 1
    assert world["listed"] == [], "an append leaves every directory unchanged, so no directory is listed"
    _age_tree(corpus)

    (slug / f"{E}.jsonl").write_bytes(_line("e1"))
    assert _same(world, monkeypatch)["shape"]["summary"]["added"] == 1
    _age_tree(corpus)

    (slug / f"{B}.jsonl").unlink()
    assert _same(world, monkeypatch)["shape"]["summary"]["removed"] == 1
    gone_b = _identity(world["db"], B)
    assert gone_b is not None
    _age_tree(corpus)

    (slug / f"{B}.jsonl").write_bytes(_line("b9"))
    monkeypatch.setattr(refresh_mod, "utc_now", lambda: LATER)
    assert _same(world, monkeypatch)["shape"]["summary"]["added"] == 1
    assert _identity(world["db"], B) == gone_b, "the returning file carries the id and first_seen of its gone row"
    assert gone_b[1] != LATER
    _age_tree(corpus)

    (slug / f"{A}.jsonl").write_bytes(_line("a1"))
    assert _same(world, monkeypatch)["shape"]["summary"]["rewritten"] == 1
    _age_tree(corpus)

    scratch = slug / "swap.tmp"
    scratch.write_bytes(_line("z1") + _line("z2") + _line("z3"))
    os.replace(scratch, slug / f"{C}.jsonl")
    assert _same(world, monkeypatch)["shape"]["summary"]["rewritten"] == 1
    _age_tree(corpus)

    (slug / E / "subagents" / "workflows" / "wf_1").mkdir(parents=True)
    (slug / E / "subagents" / "workflows" / "wf_1" / "agent-9.jsonl").write_bytes(_line("w1"))
    (corpus / "-Users-x-other").mkdir()
    (corpus / "-Users-x-other" / f"{B}.jsonl").write_bytes(_line("o1"))
    shape = _same(world, monkeypatch)["shape"]
    assert shape["summary"]["added"] == 2
    _age_tree(corpus)

    with closing(sqlite3.connect(world["db"])) as other:
        other.execute(f"UPDATE {K.TABLE} SET size = size + 7 WHERE path LIKE ?", (f"%{E}.jsonl",))
        other.commit()
    assert _same(world, monkeypatch)["shape"]["summary"]["rewritten"] == 1


def test_a_pass_with_nothing_changed_loads_only_present_rows(world, monkeypatch) -> None:
    _prime(world)
    slug = world["slug"]
    for name in (B, C):
        (slug / f"{name}.jsonl").unlink()
    _pass(world)
    _age_tree(world["corpus"])
    with closing(sqlite3.connect(world["db"])) as conn:
        gone = conn.execute(f"SELECT COUNT(*) FROM {K.TABLE} WHERE gone_at IS NOT NULL").fetchone()[0]
        present = conn.execute(f"SELECT COUNT(*) FROM {K.TABLE} WHERE gone_at IS NULL").fetchone()[0]
    assert (gone, present) == (2, 2)
    built: List[int] = []
    real_build = store.Row.from_values
    monkeypatch.setattr(store.Row, "from_values", classmethod(lambda cls, values: built.append(1) or real_build(values)))
    result = _pass(world)
    assert result.counts[K.OUT_UNCHANGED] == present
    assert len(built) == present, "only the present rows are built; the two gone rows stay in the database"


def test_an_unchanged_directory_hands_back_the_entries_it_gave_last_pass(world, monkeypatch) -> None:
    _prime(world)
    scandirs: List[str] = []
    real = os.scandir
    monkeypatch.setattr(D.os, "scandir", lambda p: scandirs.append(str(p)) or real(p))
    roots = (world["corpus"],)
    first = shared.merged_claude_discovery(roots, fresh=True)
    second = shared.merged_claude_discovery(roots, fresh=True)
    assert scandirs == []
    assert [e.source_path for e in first.entries] == [e.source_path for e in second.entries]
    assert all(x is y for x, y in zip(first.entries, second.entries))
    assert first.unrecognised_sample == second.unrecognised_sample == [f"-Users-x-proj/{A}/subagents/note.txt"]


def test_listing_classifies_like_pathlib(tmp_path: Path) -> None:
    (tmp_path / "file.jsonl").write_text("x")
    (tmp_path / "dir").mkdir()
    (tmp_path / "link-file").symlink_to(tmp_path / "file.jsonl")
    (tmp_path / "link-dir").symlink_to(tmp_path / "dir")
    (tmp_path / "broken").symlink_to(tmp_path / "missing")
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    expected = tuple(sorted((p.name, "f" if p.is_file() else "d" if p.is_dir() else "o") for p in tmp_path.iterdir()))
    assert D.DirListingCache().listing(tmp_path) == expected
    assert dict(expected)["link-file"] == "f" and dict(expected)["link-dir"] == "d" and dict(expected)["broken"] == "o"


def test_a_changed_directory_is_relisted_and_its_entries_rebuilt(world, monkeypatch) -> None:
    _prime(world)
    roots = (world["corpus"],)
    before = shared.merged_claude_discovery(roots, fresh=True)
    (world["slug"] / "new.jsonl").write_bytes(_line("n1"))
    after = shared.merged_claude_discovery(roots, fresh=True)
    assert len(after.entries) == len(before.entries) + 1
    assert "-Users-x-proj/new.jsonl" in [e.source_path for e in after.entries]


def test_a_row_built_from_values_equals_the_constructor() -> None:
    from dataclasses import astuple, replace

    from src.core.transcript_manifest.scan import Row

    values = ("/p/a.jsonl", "claude", "/p", "s/a.jsonl", "a", "conversation", 10, 20, "u", 0, 10, None, None, None, None,
              0, "present", "t0", "t1", "t2", None, 7)
    built = Row.from_values(values)
    assert built == Row(*values) and astuple(built) == values and hash(built) == hash(Row(*values))
    assert replace(built, size=11).size == 11 and replace(built, size=11).id == 7
    with pytest.raises(Exception):
        built.size = 1
    with pytest.raises(ValueError):
        Row.from_values(values[:-1])
