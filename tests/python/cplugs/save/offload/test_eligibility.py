
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pytest

from src.plugins.host import session_chains as host_chains
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import icloud, report
from src.plugins.save.offload import routes as offload_routes
from src.plugins.save.offload.eligibility import Evaluator
from src.plugins.save.vault.units import Scanner
from src.plugins.sdk import session_chains as sdk
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from tests.python.cplugs.save.vault_helpers import World, jsonl

ID = {n: f"00000000-0000-4000-8000-{i:012x}" for i, n in enumerate(["c1", "c2", "c3", "d1", "e1", "n1"], 1)}
LONG_AGO = time.time() - 10 * 86400


def facts(uuid: str, current: Optional[str], *, lifecycle: str = "stopped", source: str = "closed_by_user", asleep: bool = False,
          host: str = "local", archived: bool = False, active: Optional[float] = LONG_AGO) -> SessionFacts:
    return SessionFacts(uuid, f"title {uuid}", 1, host, lifecycle, source, archived, asleep, current, active)


def settle(world: World, convs: Iterable[str], age: float = 3 * 86400) -> None:
    for conv in convs:
        world.write_conversation(jsonl(5, seed=hash(conv) % 1000), conv=conv, subagents=1, tool_results=1)
        world.capture(conv)
    old = time.time() - age
    for path in [p for p in world.home.rglob("*") if p.is_file()]:
        os.utime(path, (old, old))


def evaluator(world: World, snapshot: ChainSnapshot, running: Iterable[str] = (), now: Optional[float] = None, blockers: Iterable[str] = ()) -> Evaluator:
    return Evaluator(snapshot, RunningScan(frozenset(running), 0), Scanner(world.sources), world.vault, now or time.time(), **({"blockers": tuple(blockers)} if blockers else {}))


def chain_snapshot() -> ChainSnapshot:
    return ChainSnapshot(
        sessions=(facts("S1", ID["c3"]), facts("S2", ID["d1"], source="slept_by_user", asleep=True), facts("S3", ID["e1"])),
        conversation_parents={ID["c3"]: frozenset({ID["c2"]}), ID["c2"]: frozenset({ID["c1"]})},
        session_parents={"S2": frozenset({ID["c1"]})})


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    settle(w, [ID[n] for n in ("c1", "c2", "c3", "d1", "e1")])
    return w


def test_an_asleep_sharer_blocks_the_whole_chain_and_a_closed_session_is_offloadable(world: World) -> None:
    ev = evaluator(world, chain_snapshot())
    s1 = ev.session("S1")
    assert s1 is not None and [c.conversation_id for c in s1.conversations] == [ID["c3"], ID["c2"], ID["c1"]]
    assert not s1.offloadable and s1.reasons == (C.REASON_ASLEEP,)
    by_id = {c.conversation_id: c for c in s1.conversations}
    assert by_id[ID["c1"]].owners == ("S1", "S2") and by_id[ID["c1"]].reasons == (C.REASON_ASLEEP,)
    assert by_id[ID["c2"]].eligible and by_id[ID["c3"]].eligible
    s3 = ev.session("S3")
    assert s3 is not None and s3.offloadable and s3.reasons == () and s3.bytes > 0


def test_a_live_remote_or_unknown_holder_is_named(world: World) -> None:
    snap = ChainSnapshot(sessions=(facts("L", ID["c1"], lifecycle="running", source=""), facts("R", ID["c2"], host="mac-2"), facts("U", ID["c3"], lifecycle="unknown")))
    ev = evaluator(world, snap)
    assert ev.session("L").reasons == (C.REASON_LIVE,)  # type: ignore[union-attr]
    assert ev.session("R").reasons == (C.REASON_REMOTE,)  # type: ignore[union-attr]
    assert ev.session("U").reasons == (C.REASON_UNKNOWN_STATE,)  # type: ignore[union-attr]


def test_a_pid_record_naming_the_conversation_gives_in_use(world: World, tmp_path: Path) -> None:
    registry = tmp_path / "sessions"
    registry.mkdir()
    (registry / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": ID["e1"], "status": "idle", "cwd": "/x", "startedAt": 1, "version": "2.1.283"}))
    scan = host_chains.running_from([registry])
    assert scan.conversations == frozenset({ID["e1"]}) and scan.unreadable == 0
    ev = Evaluator(chain_snapshot(), scan, Scanner(world.sources), world.vault, time.time())
    s3 = ev.session("S3")
    assert s3 is not None and not s3.offloadable and s3.reasons == (C.REASON_IN_USE,)
    (registry / "999999999.json").write_text("{torn")
    assert host_chains.running_from([registry]).unreadable == 1


def test_a_recent_file_a_missing_point_and_a_grown_file_each_block(world: World) -> None:
    world.write_conversation(jsonl(2), conv=ID["n1"], subagents=0, tool_results=0)
    grown = world.transcript(ID["e1"])
    grown.write_bytes(grown.read_bytes() + b'{"more":1}\n')
    old = time.time() - 3 * 86400
    os.utime(grown, (old, old))
    snap = ChainSnapshot(sessions=(facts("N", ID["n1"]), facts("G", ID["e1"])))
    ev = evaluator(world, snap)
    assert ev.session("N").reasons == (C.REASON_NOT_QUIET, C.REASON_NO_VAULT_POINT)  # type: ignore[union-attr]
    assert ev.session("G").reasons == (C.REASON_VAULT_BEHIND,)  # type: ignore[union-attr]


def test_a_placeholder_file_is_dataless(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.sdk.transcript_files import dataless

    marked = world.transcript(ID["e1"])
    real = dataless.is_dataless_stat
    monkeypatch.setattr(dataless, "is_dataless_stat", lambda info: real(info) or info.st_ino == os.lstat(marked).st_ino)
    ev = evaluator(world, chain_snapshot())
    assert C.REASON_DATALESS in ev.session("S3").reasons  # type: ignore[union-attr]


def test_the_snapshot_reads_sessions_and_edges_and_counts_an_archived_sleep_as_asleep(tmp_path: Path) -> None:
    from src.core.lineage import ddl

    db = sqlite3.connect(tmp_path / "t.db")
    db.execute("CREATE TABLE sessions (session_uuid TEXT, title TEXT, project_id INT, host_key TEXT, lifecycle TEXT, lifecycle_source TEXT, archived_at TEXT, "
               "claude_session_uuid TEXT, last_work_at TEXT, last_seen_running_at TEXT, created_at TEXT, working_dir TEXT)")
    db.execute(ddl.DDL_EDGES)
    db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("A", "a", 1, "local", "stopped", "slept_by_timer", "2026-01-02T00:00:00Z", "ca", None, "2026-01-01T00:00:00Z", "2025-12-01T00:00:00Z", "/Users/x/a"),
        ("B", None, None, "local", "stopped", "closed_by_user", None, None, "2026-01-05T00:00:00Z", "2026-01-01T00:00:00Z", "2025-12-01T00:00:00Z", None)])
    db.executemany("INSERT INTO lineage_edges (parent_type,parent_id,child_type,child_id,edge_kind,created_at) VALUES (?,?,?,?,?,?)", [
        ("conversation", ID["c1"], "conversation", ID["c2"], "clear", "t"), ("conversation", "c0", "session", "A", "fork", "t"),
        ("conversation", "x", "conversation", "y", "subagent", "t")])
    snap = host_chains.snapshot_from(db)
    rows = {s.session_uuid: s for s in snap.sessions}
    assert rows["A"].asleep and rows["A"].archived and not rows["B"].asleep
    assert rows["A"].working_dir == "/Users/x/a" and rows["B"].working_dir is None
    assert snap.conversation_parents == {ID["c2"]: frozenset({ID["c1"]})} and snap.session_parents == {"A": frozenset({"c0"})}
    assert rows["B"].last_active_epoch and rows["B"].last_active_epoch > rows["A"].last_active_epoch  # type: ignore[operator]
    db.execute("DROP TABLE lineage_edges")
    with pytest.raises(sdk.SessionChainsUnreadable):
        host_chains.snapshot_from(db)


def test_the_candidate_page_totals_idle_filter_and_blockers(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    young = facts("Y", ID["d1"], active=time.time())
    snap = ChainSnapshot(sessions=(facts("S1", ID["c3"]), facts("S3", ID["e1"]), young), conversation_parents={ID["c3"]: frozenset({ID["c2"]}), ID["c2"]: frozenset({ID["c1"]})})
    ev = evaluator(world, snap)
    inside = report.readiness(world.sources.claude_roots, RunningScan(frozenset(), 0), icloud_root=world.home)
    assert not inside.ready and inside.blockers == (C.BLOCKER_ICLOUD_PATH,)
    clean = report.readiness(world.sources.claude_roots, RunningScan(frozenset(), 0), icloud_root=world.state / "elsewhere")
    page = report.build_page(ev, clean, 30, None, 1)
    assert page.total_candidates == 0 and page.offloadable_any_idle.sessions == 3
    page = report.build_page(ev, clean, 0, None, 2)
    assert [v.session_uuid for v in page.candidates] and page.next_cursor == "2" and page.total_candidates == 3
    assert page.offloadable.conversations == 5 and page.offloadable.bytes == sum(c.bytes for v in ev.sessions() for c in v.conversations if c.on_disk)
    assert report.build_page(ev, clean, 0, "2", 2).next_cursor is None
    with pytest.raises(ValueError):
        report.build_page(ev, clean, 0, "-1", 2)
    def unresolvable(_path, **_kw):
        raise OSError("boom")

    monkeypatch.setattr(icloud.os.path, "realpath", unresolvable)
    assert icloud.blockers([world.projects], world.state) == [C.BLOCKER_ICLOUD_UNKNOWN]


def test_the_routes_answer_from_the_evaluator_and_refuse_an_unknown_session(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(offload_routes.session_chains, "read_snapshot", chain_snapshot)
    monkeypatch.setattr(offload_routes.session_chains, "read_running", lambda: RunningScan(frozenset(), 0))
    monkeypatch.setattr(offload_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(offload_routes.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setenv("HOME", str(world.state.parent / "fakehome"))
    out = offload_routes._session("S1")
    assert out.offloadable is False and out.reasons == [C.REASON_ASLEEP] and [c.conversation_id for c in out.conversations] == [ID["c3"], ID["c2"], ID["c1"]]
    listing = offload_routes._candidates(0, None, 50)
    assert [c.session_uuid for c in listing.candidates] == ["S3"] and listing.blocked == {C.REASON_ASLEEP: 2}
    with pytest.raises(HTTPException) as caught:
        offload_routes._session("nope")
    assert caught.value.status_code == 404


def test_no_row_is_eligible_while_an_install_wide_blocker_stands(world: World) -> None:
    ev = evaluator(world, chain_snapshot(), blockers=[C.BLOCKER_REGISTRY_UNREADABLE])
    s3 = ev.session("S3")
    assert s3 is not None and not s3.offloadable and C.REASON_NOT_READY in s3.reasons
    assert all(not c.eligible and C.REASON_NOT_READY in c.reasons for c in s3.conversations)
    blocked = report.Readiness(False, (C.BLOCKER_ICLOUD_PATH,))
    page = report.build_page(evaluator(world, chain_snapshot()), blocked, 0, None, 50)
    assert page.candidates == [] and page.offloadable.conversations == 0 and page.offloadable_any_idle.conversations == 0 and page.no_session.conversations == 0
    ready = report.build_page(evaluator(world, chain_snapshot()), report.Readiness(True, ()), 0, None, 50)
    assert [v.session_uuid for v in ready.candidates] == ["S3"]


def test_an_unlistable_registry_folder_blocks_readiness_and_only_a_missing_one_is_skipped(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "1.json").write_text("{}")
    os.chmod(locked, 0)
    try:
        scan = host_chains.running_from([locked, tmp_path / "missing"])
    finally:
        os.chmod(locked, 0o700)
    assert scan.unreadable == 1 and scan.conversations == frozenset()
    assert host_chains.running_from([tmp_path / "missing"]).unreadable == 0
    assert report.readiness([], scan).blockers == (C.BLOCKER_REGISTRY_UNREADABLE,)


def test_a_file_that_cannot_be_stat_ed_makes_its_conversation_not_eligible(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.save.offload import eligibility

    real = os.lstat

    def lstat(path, *a, **k):
        if "tool-results" in str(path):
            raise PermissionError(13, "denied", str(path))
        return real(path, *a, **k)

    monkeypatch.setattr(eligibility.os, "lstat", lstat)
    s3 = evaluator(world, chain_snapshot()).session("S3")
    assert s3 is not None and not s3.offloadable and C.REASON_UNREADABLE_FILE in s3.reasons


def test_a_dead_pane_with_a_conversation_is_asleep_and_one_without_is_not(tmp_path: Path) -> None:
    from src.core.lineage import ddl

    db = sqlite3.connect(tmp_path / "t.db")
    db.execute("CREATE TABLE sessions (session_uuid TEXT, title TEXT, project_id INT, host_key TEXT, lifecycle TEXT, lifecycle_source TEXT, archived_at TEXT, "
               "claude_session_uuid TEXT, last_work_at TEXT, last_seen_running_at TEXT, created_at TEXT, working_dir TEXT)")
    db.execute(ddl.DDL_EDGES)
    db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("D1", None, None, "local", "stopped", "pane_dead", None, "conv", None, None, "2026-01-01T00:00:00Z", None),
        ("D2", None, None, "local", "stopped", "pane_dead", None, None, None, None, "2026-01-01T00:00:00Z", None),
        ("D3", None, None, "local", "running", "pane_dead", None, "conv", None, None, "2026-01-01T00:00:00Z", None)])
    rows = {s.session_uuid: s.asleep for s in host_chains.snapshot_from(db).sessions}
    assert rows == {"D1": True, "D2": False, "D3": False}
