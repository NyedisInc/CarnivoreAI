
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from typing import Dict, List

import httpx
import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
import structlog  # noqa: E402

from src.core.argent import notices, pair_sync  # noqa: E402
from src.core.argent.delegate import Delegates  # noqa: E402
from src.core.computers import mesh, mesh_removal  # noqa: E402
from src.core.computers.runtime import LazyPack  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import peer_hosts  # noqa: E402
from src.core.pack.jobs import boot, runner  # noqa: E402
from src.core.pack.jobs.host import Host  # noqa: E402
from src.core.pack.jobs.store import JobStore  # noqa: E402
from src.core.pack.jobs.types import HostJob, HostState  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, settings_doc  # noqa: E402
from src.core.pack.meshdata import envelope, gossip  # noqa: E402
from src.core.pack.meshdata.store import RecordStore  # noqa: E402
from src.core.pack.relay import approval, member_reach, retire  # noqa: E402
from src.core.pack.rollup_import import ddl as rollup  # noqa: E402
from tests.argent.test_argent_refresh import T0, Rig  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.python.pack.test_mesh_settings import machines, net  # noqa: E402,F401
from tests.python.pack.test_roster import _inputs  # noqa: E402
from tests.python.pack.test_settings_signing import IDS, make_pack, mesh as settle  # noqa: E402

@pytest.fixture(autouse=True)
def _fresh_member_cache(monkeypatch):
    monkeypatch.setattr(member_reach, "_LAST_GOOD", None)


A, B, C = IDS["a"], IDS["b"], IDS["c"]
X, X2, S = "install-x1", "install-x2", "install-star"


class Clock:

    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


class Held:

    def __init__(self) -> None:
        self.lst = None

    def __call__(self):
        return self.lst


async def drain(removal) -> None:
    task = removal._task
    if task is not None:
        await task


async def deliver(removal, box: Held, lst, in_grace: bool = False) -> None:
    box.lst = lst
    await removal.list_changed(lst, in_grace)
    await drain(removal)


def _fake(iid: str, n: int) -> roster_doc.RosterInput:
    base = _inputs(("a",))[0]
    return roster_doc.RosterInput(install_id=iid, label=iid, fed_public_key=base.fed_public_key, cert=bytes([n]) * 40, next_cert=None,
                                  addresses=(), link_port=47110, relay_id=None)


def _stats(conn: sqlite3.Connection, iid: str) -> tuple:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE peer_install_id = ?", (iid,)).fetchone()[0]
                 for t in (rollup.USAGE_TABLE, rollup.STATE_TABLE, rollup.FLOOR_TABLE))


def _seed(conn: sqlite3.Connection, iid: str) -> None:
    conn.execute(f"INSERT OR REPLACE INTO {rollup.USAGE_TABLE} (peer_install_id, conversation_id, hour, model, project) VALUES (?, 'conv', 1, 'm', 'p')", (iid,))
    conn.execute(f"INSERT OR REPLACE INTO {rollup.STATE_TABLE} (peer_install_id) VALUES (?)", (iid,))
    conn.execute(f"INSERT OR REPLACE INTO {rollup.FLOOR_TABLE} (peer_install_id, conversation_id, hour, floor) VALUES (?, 'conv', 1, 5)", (iid,))
    conn.commit()
    approval.record(conn, iid, "yes")


def _answers(conn: sqlite3.Connection) -> Dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT install_id, answer FROM pack_relay_approval")}


def test_a_signed_list_without_x_purges_x_on_this_member_and_an_older_list_never_brings_it_back(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    mesh_removal._REFUSED_LOGGED.clear()
    (tmp_path / "pack").mkdir()
    pack = make_pack(tmp_path / "pack", {}, None)
    a, b = pack["a"], pack["b"]
    settle(pack, 2)
    fakes = [_fake(X, 7), _fake(X2, 8)]
    wires: Dict[str, dict] = {}
    real = _inputs(("a", "b", "c"))
    plans = {"N": real + fakes, "N1": real + [fakes[1]], "N2": real, "N3": real + [fakes[0]]}
    custody = b.custody
    wire_lists: Dict[str, object] = {}
    for name, inputs in plans.items():
        assert a.refresh_roster(inputs).startswith("bump")
        wires[name] = json.loads(json.dumps(a.custody.roster_v2_wire()))
        wire_lists[name] = a.custody.roster_v2()
    assert [wire_lists[n].generation for n in plans] == sorted(wire_lists[n].generation for n in plans) and len({wire_lists[n].generation for n in plans}) == 4
    assert all(wire_lists["N"].entry(i) is not None for i in (X, X2)) and wire_lists["N1"].entry(X) is None
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state)
    open_db = lambda: connect(db_path_for(state), create=False)  # noqa: E731
    clock = Clock()
    stopped: List[str] = []
    monkeypatch.setattr(runner, "stop", lambda job_id, **kw: stopped.append(job_id))
    host = Host(state_dir=state, jobs_root=state / "jobs", install_id=B, store=JobStore(state), open_db=open_db, clock=clock)

    async def no_worker(job_id):
        return None

    monkeypatch.setattr(host.agent, "stop_worker_of", no_worker)
    monkeypatch.setitem(boot._built, "host", host)
    for jid, caller in (("job_aaaaaaaaaaaa", X), ("job_bbbbbbbbbbbb", C)):
        host.store.host_put(HostJob(job_id=jid, caller_install=caller, project_uid="p", state=HostState.RUNNING, started_at=clock.t))
    records = RecordStore(tmp_path / "records.db", B)
    kid = lambda lst, iid: envelope.kid(lst.entry(iid).fed_public_key)  # noqa: E731
    with closing(sqlite3.connect(records.path)) as raw:
        for origin in (C, X, A):
            raw.execute("INSERT INTO records (kind, key, value_json, ms, ctr, origin, h, sig_json, kid, direct, received_ms) VALUES ('status', ?, '{}', 5, 0, ?, 'h', '{}', ?, 0, 5)",
                        (origin, origin, kid(wire_lists["N"], origin)))
        raw.commit()
    monkeypatch.setattr(gossip, "ACTIVE", SimpleNamespace(store=records))

    def record_origins() -> set:
        with closing(sqlite3.connect(records.path)) as raw:
            return {r[0] for r in raw.execute("SELECT origin FROM records")}

    retired: List[str] = []
    answer = {"outcome": {}}

    async def retire_from(iid: str) -> Dict[str, str]:
        retired.append(iid)
        return dict(answer["outcome"])

    notified: List[str] = []
    box = Held()
    steps = dataclasses.replace(mesh_removal.production_steps(notified.append, box), retire_from=retire_from)
    removal = mesh_removal.Removal(open_db=open_db, self_iid=B, steps=steps, held=box, clock=clock)

    def table_exists() -> bool:
        with closing(open_db()) as conn:
            return mesh_removal._exists(conn)

    async def scenario() -> None:
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
        await deliver(removal, box, wire_lists["N"])
        assert not table_exists()
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
        await deliver(removal, box, wire_lists["N"], in_grace=True)
        await deliver(removal, box, a.custody.roster())
        assert not table_exists()
        await deliver(removal, box, wire_lists["N"])
        with closing(open_db()) as conn:
            rows = mesh_removal.read_rows(conn)
            assert {i: r.state for i, r in rows.items()} == {i: "listed" for i in (A, B, C, X, X2)}
        assert retired == [] and not stopped
        with closing(open_db()) as conn:
            for iid in (X, X2, C, A, S):
                _seed(conn, iid)
            peer_hosts.upsert(conn, install_id=S, label="star", grant_id="gs", fid="fs", initiator=True)
            mesh_row = peer_hosts.upsert_mesh(conn, install_id=X, label="x", grant_id="gx", fid="fx")
            conn.execute("INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, lifecycle, lifecycle_source, created_at, updated_at) "
                         "VALUES ('u1', 'observed', 'carnivore', 'n', 1, 'running', 'import', 't', 't')")
            conn.execute("INSERT INTO peer_sessions (host_key, peer_session_uuid, peer_name, session_id) VALUES (?, 'u1', 'n', last_insert_rowid())", (mesh_row.key,))
            conn.commit()
            assert peer_hosts.get(conn, X, include_mesh=True) is not None
        assert custody.merge_roster_v2(wires["N"], A) and custody.merge_roster_v2(wires["N1"], A)
        held = custody.held_lists()[0]
        assert held.generation == wire_lists["N1"].generation and held.entry(X) is None
        await deliver(removal, box, held)
        with closing(open_db()) as conn:
            assert _stats(conn, X) == (0, 0, 1)
            assert peer_hosts.get(conn, X, include_mesh=True) is None
            assert conn.execute("SELECT COUNT(*) FROM peer_sessions").fetchone()[0] == 0
            assert X not in _answers(conn)
            for iid in (X2, C, A, S):
                assert _stats(conn, iid) == (1, 1, 1), iid
            assert {X2, C, A, S} <= set(_answers(conn))
            assert peer_hosts.get(conn, S) is not None
            assert mesh_removal.read_rows(conn)[X].state == "removed" and mesh_removal.read_rows(conn)[X].passes == 1
        assert record_origins() == {C, A}
        assert retired == [X]
        assert host.store.host_get("job_aaaaaaaaaaaa").state == HostState.FAILED and host.store.host_get("job_aaaaaaaaaaaa").detail.startswith("peer_left")
        assert host.store.host_get("job_bbbbbbbbbbbb").state == HostState.RUNNING and stopped == ["job_aaaaaaaaaaaa"]
        assert {"computers", "pack_machines", "pack_relay_offer"} <= set(notified)
        assert custody.merge_roster_v2(wires["N"], A) is False and custody.held_lists()[0].generation == held.generation
        with structlog.testing.capture_logs() as logs:
            await deliver(removal, box, wire_lists["N"])
        assert any(e["event"] == "mesh_removal_relist_refused" for e in logs)
        box.lst = held
        with closing(open_db()) as conn:
            assert mesh_removal.read_rows(conn)[X].state == "removed" and _stats(conn, X) == (0, 0, 1)
            assert _stats(conn, X2) == (1, 1, 1)
        with closing(open_db()) as conn:
            _seed(conn, X)
        answer["outcome"] = {"work": retire.DEFERRED}
        clock.t += mesh_removal.RETRY_SECONDS
        await removal.pass_once()
        with closing(open_db()) as conn:
            assert _stats(conn, X) == (0, 0, 1) and X not in _answers(conn)
            row = mesh_removal.read_rows(conn)[X]
            assert row.state == "removed" and row.passes == 1
        clock.t += mesh_removal.SETTLE_SECONDS
        answer["outcome"] = {"work": retire.REMOVED}
        await removal.pass_once()
        with closing(open_db()) as conn:
            assert mesh_removal.read_rows(conn)[X].state == "purged"
        seen = len(retired)
        await removal.pass_once()
        assert len(retired) == seen and removal.pending() == []
        with closing(open_db()) as conn:
            peer_hosts.upsert(conn, install_id=X2, label="x2", grant_id="g2", fid="f2", initiator=True)
        assert custody.merge_roster_v2(wires["N2"], A)
        with structlog.testing.capture_logs() as logs:
            await deliver(removal, box, custody.held_lists()[0])
        assert any(e["event"] == "mesh_removal_star_kept" for e in logs)
        with closing(open_db()) as conn:
            assert _stats(conn, X2) == (1, 1, 1) and X2 in _answers(conn)
        assert custody.merge_roster_v2(wires["N3"], A)
        await deliver(removal, box, custody.held_lists()[0])
        with closing(open_db()) as conn:
            states = {i: r.state for i, r in mesh_removal.read_rows(conn).items()}
            assert states[X] == "listed" and states[C] == "listed" and states[X2] != "listed"
        await removal.stop()

    asyncio.run(scenario())
    with closing(open_db()) as conn:
        peer_hosts.upsert_mesh(conn, install_id=C, label="c", grant_id="gc", fid="fc")
        _seed(conn, C)
    assert mesh_removal.leave_mesh_rows(open_db) == [C]
    with closing(open_db()) as conn:
        assert peer_hosts.get(conn, C, include_mesh=True) is None and _stats(conn, C) == (0, 0, 1)
        assert peer_hosts.get(conn, S) is not None and _stats(conn, S) == (1, 1, 1)
        assert mesh_removal.read_rows(conn) == {}


def test_compose_on_list_awaits_each_hook_in_order():
    seen: List[str] = []

    def hook(name: str):
        async def run(lst, in_grace):
            seen.append(f"{name}:{lst}:{in_grace}")
        return run

    asyncio.run(mesh.compose_on_list(hook("peers"), hook("removal"))("L", True))
    assert seen == ["peers:L:True", "removal:L:True"]


def test_plan_is_pure_and_refuses_an_equal_generation():
    from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2

    def lst(gen: int, *ids: str) -> RosterV2:
        rows = [RosterComputerV2(install_id=i, label=i, fed_public_key=ss.PUB[A], cert=base64.b64encode(b"x" * 40).decode(), mesh=True) for i in ids]
        return RosterV2(generation=gen, alpha=ids[0], home=ids[0], issued_at=1, computers=rows)

    first = mesh_removal.plan({}, lst(3, "a", "b", "x"), "b")
    assert first.insert == {"a": 3, "b": 3, "x": 3} and not first.remove
    rows = {i: mesh_removal.Row("listed", 3, None, 0, None) for i in ("a", "b", "x")}
    assert mesh_removal.plan(rows, lst(3, "a", "b"), "b").remove == {}
    assert mesh_removal.plan(rows, lst(4, "a", "b"), "b").remove == {"x": 4}
    assert mesh_removal.plan(rows, lst(4, "a", "x"), "b").remove == {}
    gone = {**rows, "x": mesh_removal.Row("removed", 4, 1.0, 1, 2.0)}
    assert mesh_removal.plan(gone, lst(4, "a", "b", "x"), "b").refused == ("x",)
    assert mesh_removal.plan(gone, lst(5, "a", "b", "x"), "b").relist == {"x": 5}


def _signed_lists(tmp_path, *plans):
    (tmp_path / "pack").mkdir()
    pack = make_pack(tmp_path / "pack", {}, None)
    settle(pack, 2)
    out = []
    for inputs in plans:
        assert pack["a"].refresh_roster(inputs).startswith("bump")
        out.append(pack["a"].custody.roster_v2())
    return out


def _tmp_db(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    ensure_db_migrated(state)
    return lambda: connect(db_path_for(state), create=False)


def _quiet_steps(**over):
    base = dict(retire_from=_async_const({}), end_jobs=_async_const(0), records=lambda: None, notify=lambda topic: None)
    base.update(over)
    return mesh_removal.Steps(**base)


def test_a_pack_leave_never_lets_the_old_packs_list_drive_a_sweep_even_when_a_stale_hook_fires_after_it(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    low_with_x, low_without_x, old_high = _signed_lists(tmp_path, real + [x], real, real + [x])
    assert old_high.generation > low_without_x.generation
    open_db, clock, box, reconciled = _tmp_db(tmp_path), Clock(), Held(), []
    removal = mesh_removal.Removal(open_db, B, _quiet_steps(records=lambda: reconciled.append(box.lst)), box, clock)

    async def run() -> None:
        await deliver(removal, box, old_high)
        box.lst = None
        with closing(open_db()) as conn:
            mesh_removal.clear(conn)
        await removal.list_changed(old_high, False)
        await drain(removal)
        with closing(open_db()) as conn:
            assert mesh_removal.read_rows(conn) == {}
        await deliver(removal, box, low_with_x)
        await deliver(removal, box, low_without_x)
        assert removal.pending() == [X]
        clock.t += mesh_removal.SETTLE_SECONDS + 1
        removal._retry()
        await drain(removal)
        assert removal.pending() == [] and reconciled and all(lst is low_without_x for lst in reconciled)
        await removal.stop()

    asyncio.run(run())


def test_a_records_step_whose_store_is_cleared_between_its_generation_and_its_list_read_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    store = RecordStore(tmp_path / "records.db", B)
    (lst,) = _signed_lists(tmp_path, _inputs(("a", "b", "c")))

    def origins() -> set:
        with closing(sqlite3.connect(store.path)) as raw:
            return {r[0] for r in raw.execute("SELECT origin FROM records")}

    def wipe_then_new_pack_row() -> object:
        store.clear()
        with closing(sqlite3.connect(store.path)) as raw:
            raw.execute("INSERT INTO records (kind, key, value_json, ms, ctr, origin, h, sig_json, kid, direct, received_ms) VALUES ('status', ?, '{}', 5, 0, ?, 'h', '{}', 'k', 0, 5)", (X, X))
            raw.commit()
        return lst

    monkeypatch.setattr(gossip, "ACTIVE", SimpleNamespace(store=store))
    mesh_removal.production_steps(lambda topic: None, wipe_then_new_pack_row).records()
    assert origins() == {X}
    store.reconcile(lst)
    assert origins() == set()


def test_clear_roster_and_a_join_of_another_pack_empty_the_removal_table_and_a_join_of_the_same_pack_keeps_it(net, tmp_path, monkeypatch):  # noqa: F811
    n = net("a", "b", "c")
    held = [(n.lst(), None)]
    rt = machines(tmp_path, n, "b")
    rt.custody.held_lists = lambda: held[0]  # type: ignore[method-assign]
    pack = LazyPack(lambda: SimpleNamespace(runtime=rt))
    doc_a = settings_doc.default_doc(n.iid["a"])
    open_db = _tmp_db(tmp_path)
    monkeypatch.setattr(mesh_removal, "REMOVAL", mesh_removal.Removal(open_db, B, _quiet_steps(), Held()))

    def fill() -> None:
        with closing(open_db()) as conn:
            mesh_removal._ensure(conn)
            conn.execute("INSERT OR REPLACE INTO pack_mesh_removal (install_id, state, generation) VALUES (?, 'removed', 9)", (X,))
            conn.commit()

    def rows() -> dict:
        with closing(open_db()) as conn:
            return mesh_removal.read_rows(conn)

    fill()
    pack.adopt(doc_a)
    assert X in rows()
    pack.adopt(settings_doc.default_doc(n.iid["c"]))
    assert rows() == {}
    fill()
    rt.custody.adopt(doc_a)
    held[0] = (n.lst(), None)
    pack.clear_roster()
    assert rows() == {}


def test_a_read_that_fails_on_a_timer_run_ends_the_task_cleanly_and_arms_the_next_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    with_x, without_x = _signed_lists(tmp_path, real + [x], real)
    open_db, clock, box = _tmp_db(tmp_path), Clock(), Held()
    removal = mesh_removal.Removal(open_db, B, _quiet_steps(), box, clock)

    async def run() -> None:
        await deliver(removal, box, with_x)
        await deliver(removal, box, without_x)
        assert removal.pending() == [X]
        real_read = removal._read

        def locked() -> dict:
            raise sqlite3.OperationalError("database is locked")

        removal._read = locked  # type: ignore[method-assign]
        removal._retry()
        await drain(removal)
        assert removal._task.exception() is None and removal._timer is not None
        removal._read = real_read  # type: ignore[method-assign]
        clock.t += mesh_removal.SETTLE_SECONDS + 1
        removal._retry()
        await drain(removal)
        assert removal.pending() == []
        await removal.stop()

    asyncio.run(run())


def test_a_slow_sweep_does_not_hold_the_list_hook_and_a_newer_list_is_never_overtaken(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    with_x, without_x, with_x_again = _signed_lists(tmp_path, real + [x], real, real + [x])
    open_db, box = _tmp_db(tmp_path), Held()

    async def run() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        async def end_jobs(_iid: str) -> int:
            entered.set()
            await release.wait()
            return 0

        removal = mesh_removal.Removal(open_db, B, _quiet_steps(end_jobs=end_jobs), box, Clock())
        await deliver(removal, box, with_x)
        box.lst = without_x
        await asyncio.wait_for(removal.list_changed(without_x, False), 1)
        await asyncio.wait_for(entered.wait(), 5)
        box.lst = with_x_again
        await asyncio.wait_for(removal.list_changed(with_x_again, False), 1)
        assert not removal._task.done()
        release.set()
        await drain(removal)
        with closing(open_db()) as conn:
            assert mesh_removal.read_rows(conn)[X].state == "listed"
        await removal.stop()

    asyncio.run(run())


def test_an_unstarted_relay_is_not_a_clean_pass_and_a_started_one_with_nothing_to_retire_purges(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    with_x, without_x = _signed_lists(tmp_path, real + [x], real)
    open_db, clock, box = _tmp_db(tmp_path), Clock(), Held()
    answer = {"outcome": None}

    async def retire_from(_iid: str):
        return answer["outcome"]

    removal = mesh_removal.Removal(open_db, B, _quiet_steps(retire_from=retire_from), box, clock)

    def state() -> str:
        with closing(open_db()) as conn:
            return mesh_removal.read_rows(conn)[X].state

    async def run() -> None:
        await deliver(removal, box, with_x)
        with structlog.testing.capture_logs() as logs:
            await deliver(removal, box, without_x)
            for _ in range(3):
                clock.t += mesh_removal.SETTLE_SECONDS + 1
                await removal.pass_once()
        assert state() == "removed" and [e["event"] for e in logs].count("mesh_removal_relay_not_started") == 1
        answer["outcome"] = {}
        for _ in range(2):
            clock.t += mesh_removal.MIN_PASS_GAP
            await removal.pass_once()
        assert state() == "purged"
        await removal.stop()

    asyncio.run(run())


def test_the_refused_log_set_is_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    mesh_removal._REFUSED_LOGGED.clear()
    (lst,) = _signed_lists(tmp_path, _inputs(("a", "b", "c")) + [_fake(X, 7)])
    open_db, box = _tmp_db(tmp_path), Held()
    with closing(open_db()) as conn:
        mesh_removal._ensure(conn)
        conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation) VALUES (?, 'removed', 100000)", (X,))
        conn.commit()
    removal = mesh_removal.Removal(open_db, B, _quiet_steps(), box)
    for generation in range(1, 301):
        box.lst = lst.model_copy(update={"generation": generation})
        removal._write_plan()
    assert 0 < len(mesh_removal._REFUSED_LOGGED) <= mesh_removal._REFUSED_CAP



def _argent_world(monkeypatch, tmp_path, delete_status=None, live=("dlg-x", "dlg-c")):
    monkeypatch.setattr(notices, "pair_login", lambda computer: None)
    rig = Rig(tmp_path / "argent")
    deletes: List[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deletes.append(request.url.path)
            if delete_status:
                return httpx.Response(delete_status, json={"error": {"code": "x"}})
        return await rig.argent.handle(request)

    for ident in live:
        rig.argent.live[ident] = "DELEGATE-token-fixture-" + ident
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"argent": {}}))
    sync = pair_sync.PairSync(store=rig.store, tokens=rig.tokens, self_id=B, self_label="b", peer=lambda _iid: None, listing=lambda: [], candidates=lambda: [],
                              allows=lambda _iid: True, config_path=cfg_dir / "config.json", state_dir=cfg_dir, clock=lambda: rig.now[0])
    sync.credentials._delegates = Delegates(rig.store, rig.tokens, read_settings=lambda: rig.cfg, transport=httpx.MockTransport(handler), clock=lambda: rig.now[0])
    expiry = int((T0 + 86400) * 1000)
    for iid, ident in ((X, "dlg-x"), (C, "dlg-c")):
        rig.store.delegate_put(iid, {"id": ident, "expires_at": expiry, "remint_at": expiry, "stale": []})
    return sync, rig, deletes


def test_a_signed_list_without_x_kills_its_argent_delegate_in_the_same_sweep_and_an_unreadable_list_kills_none(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    n_list, n1_list = _signed_lists(tmp_path, real + [x], real)
    clock, box = Clock(), Held()

    def removal_for(sync, tag):
        db = _tmp_db(tmp_path / tag)
        return mesh_removal.Removal(db, B, _quiet_steps(revoke_delegates=sync.revoke_removed), box, clock), db

    async def sweep(removal) -> None:
        await deliver(removal, box, n_list)
        await deliver(removal, box, n1_list)

    sync, rig, deletes = _argent_world(monkeypatch, tmp_path / "one")
    asyncio.run(sweep(removal_for(sync, "db-one")[0]))
    assert deletes == ["/v1/my/cli/delegates/dlg-x"] and rig.store.delegate_get(X) is None and rig.store.delegate_get(C) is not None
    assert sync.credentials.sent[X]["state"] == "dead" and "dlg-x" not in rig.argent.live and "dlg-c" in rig.argent.live

    for forced, live in ((500, ("dlg-x", "dlg-c")), (None, ("dlg-c",))):
        sync, rig, deletes = _argent_world(monkeypatch, tmp_path / f"two{forced}", delete_status=forced, live=live)
        removal, open_db = removal_for(sync, f"db-two{forced}")

        async def settle_row() -> None:
            await sweep(removal)
            for _ in range(2):
                clock.t += mesh_removal.SETTLE_SECONDS + 1
                await removal.pass_once()
            await removal.stop()

        asyncio.run(settle_row())
        record = rig.store.delegate_get(X)
        assert sync.credentials.sent[X]["state"] == "pending" and record is not None and record["stale"][0]["id"] == "dlg-x"
        with closing(open_db()) as conn:
            assert mesh_removal.read_rows(conn)[X].state == "purged"

    sync, rig, deletes = _argent_world(monkeypatch, tmp_path / "three")
    custody = SimpleNamespace(state="ok", v2=n_list, master=A)

    def held_lists():
        if custody.state == "raise":
            raise OSError("unreadable")
        if custody.state == "v1":
            return (SimpleNamespace(), None)
        return (custody.v2, None)

    custody.held_lists, custody.roster_v2 = held_lists, lambda: custody.v2
    custody.settings = lambda: SimpleNamespace(master_install_id=custody.master)
    monkeypatch.setattr(member_reach.machines_runtime, "wiring", lambda: SimpleNamespace(runtime=SimpleNamespace(custody=custody, install_id=B)))
    monkeypatch.setattr(member_reach, "ids_in", lambda lst: [c.install_id for c in lst.computers if c.install_id not in (B, lst.alpha)])
    sender = sync.credentials
    sender._candidates, sender._frozen = member_reach.member_ids, member_reach.list_unknown
    sender._approved = lambda _iid: member_reach.list_state()[0] == "ok"
    good = member_reach.member_ids()
    assert set(good) == {C, X}
    custody.state = "raise"
    asyncio.run(sender.push(None))
    assert deletes == [] and sorted(member_reach.member_ids()) == sorted(good)
    custody.state = "v1"
    asyncio.run(sender.push(None))
    assert deletes == [] and member_reach.list_unknown()
    sender._denied = lambda iid: iid == C
    asyncio.run(sender.push(None))
    assert deletes == ["/v1/my/cli/delegates/dlg-c"] and rig.store.delegate_get(X) is not None
    sender._denied = lambda _iid: False
    rig.store.delegate_put(C, {"id": "dlg-c", "expires_at": int((T0 + 86400) * 1000), "remint_at": int((T0 + 86400) * 1000), "stale": []})
    deletes.clear()
    custody.state = "raise"
    sender._frozen = lambda: False
    asyncio.run(sender.push(None))
    assert sorted(deletes) == ["/v1/my/cli/delegates/dlg-c", "/v1/my/cli/delegates/dlg-x"]
    custody.master = B
    assert member_reach.member_ids() == []
    custody.master = A
    assert member_reach.member_ids() == []


def _async_const(value):
    async def answer(_iid):
        return value

    return answer


def _frozen_sender(monkeypatch, tmp_path, candidates, frozen=lambda: True, denied=lambda _iid: False):
    sync, rig, deletes = _argent_world(monkeypatch, tmp_path)
    sender = sync.credentials
    sender._candidates, sender._frozen, sender._denied = (lambda: list(candidates)), frozen, denied
    sender._approved = lambda _iid: False
    return sync, rig, deletes


def test_m1a_a_frozen_sender_with_an_empty_member_cache_and_star_candidates_kills_no_member_delegate(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    sync, rig, deletes = _frozen_sender(monkeypatch, tmp_path, [A])
    asyncio.run(sync.credentials.push(None))
    assert deletes == [] and rig.store.delegate_get(C) is not None and rig.store.delegate_get(X) is not None


def test_m1b_frozen_plus_a_local_no_for_an_unlisted_id_kills_just_that_one(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    sync, rig, deletes = _frozen_sender(monkeypatch, tmp_path, [A], denied=lambda iid: iid == X)
    asyncio.run(sync.credentials.push(None))
    assert deletes == ["/v1/my/cli/delegates/dlg-x"] and rig.store.delegate_get(C) is not None


def test_m1e_frozen_plus_a_computer_marked_one_way_kills_its_delegate(monkeypatch, tmp_path):
    from src.core.computers import direction, store as computers_store  # noqa: PLC0415

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(computers_store, "CACHE", {X: SimpleNamespace(inbound_control=0), C: SimpleNamespace(inbound_control=1)})
    sync, rig, deletes = _frozen_sender(monkeypatch, tmp_path, [A], denied=direction.contained)
    asyncio.run(sync.credentials.push(None))
    assert deletes == ["/v1/my/cli/delegates/dlg-x"] and rig.store.delegate_get(C) is not None


def test_m1c_a_denied_read_that_fails_while_frozen_kills_nothing_and_the_pass_is_logged(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)

    def denied(_iid: str) -> bool:
        raise sqlite3.OperationalError("unreadable")

    sync, rig, deletes = _frozen_sender(monkeypatch, tmp_path, [A], denied=denied)
    with structlog.testing.capture_logs() as logs:
        asyncio.run(sync._push_credentials(None))
    assert deletes == [] and "argent_pair_credential_pass_failed" in [e["event"] for e in logs]
    assert rig.store.delegate_get(C) is not None and rig.store.delegate_get(X) is not None


def test_m1d_a_list_that_turns_unknown_after_the_pass_began_revokes_no_listed_member(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    reads = iter([False] + [True] * 20)
    sync, rig, deletes = _frozen_sender(monkeypatch, tmp_path, [C, X], frozen=lambda: next(reads))
    asyncio.run(sync.credentials.push(None))
    assert deletes == [] and rig.store.delegate_get(C) is not None and rig.store.delegate_get(X) is not None


def test_m2_forget_pack_clears_the_table_through_the_database_when_no_sweep_is_attached(monkeypatch, tmp_path):
    from src.core.pack.machines import runtime as machines_runtime

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    open_db = _tmp_db(tmp_path)
    with closing(open_db()) as conn:
        mesh_removal._ensure(conn)
        conn.execute("INSERT INTO pack_mesh_removal (install_id, state, generation) VALUES ('iid-x', 'removed', 3)")
        conn.commit()
    monkeypatch.setattr(mesh_removal, "REMOVAL", None)
    monkeypatch.setattr(machines_runtime, "wiring", lambda: None)
    assert mesh_removal.forget_pack() is False
    monkeypatch.setattr(machines_runtime, "wiring", lambda: SimpleNamespace(open_db=open_db, runtime=SimpleNamespace()))
    assert mesh_removal.forget_pack() is True
    with closing(open_db()) as conn:
        assert mesh_removal.read_rows(conn) == {}


def test_m3_two_passes_at_one_clock_count_once_and_a_stopped_sweep_has_ended_when_stop_returns(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh_removal, "STOP_WAIT", 0.05)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    with_x, without_x = _signed_lists(tmp_path, real + [x], real)
    open_db, clock, box = _tmp_db(tmp_path), Clock(), Held()
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_end_jobs(_iid: str) -> int:
        entered.set()
        await release.wait()
        return 0

    async def run() -> None:
        removal = mesh_removal.Removal(open_db, B, _quiet_steps(), box, clock)
        await deliver(removal, box, with_x)
        with closing(open_db()) as conn, conn:
            conn.execute("UPDATE pack_mesh_removal SET state = 'removed', removed_at = ? WHERE install_id = ?", (clock.t - 10_000, X))

        def row():
            with closing(open_db()) as conn:
                return mesh_removal.read_rows(conn)[X]

        removal._settle(X)
        removal._settle(X)
        assert row().passes == 1
        clock.t += mesh_removal.MIN_PASS_GAP
        removal._settle(X)
        assert row().passes == 2 and row().state == "purged"
        stuck = mesh_removal.Removal(open_db, B, _quiet_steps(end_jobs=blocked_end_jobs), box, clock)
        with closing(open_db()) as conn, conn:
            conn.execute("UPDATE pack_mesh_removal SET state = 'listed', removed_at = NULL, passes = 0, last_pass = NULL WHERE install_id = ?", (X,))
        box.lst = with_x
        box.lst = without_x
        await stuck.list_changed(without_x, False)
        await asyncio.wait_for(entered.wait(), 5)
        await stuck.stop()
        assert stuck._task.done()
        release.set()

    asyncio.run(run())


def test_m5_a_retry_that_only_meets_an_unstarted_relay_notifies_once_and_reaching_purged_notifies_again(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    real, x = _inputs(("a", "b", "c")), _fake(X, 7)
    with_x, without_x = _signed_lists(tmp_path, real + [x], real)
    open_db, clock, box, told = _tmp_db(tmp_path), Clock(), Held(), []
    answer = {"outcome": None}

    async def retire_from(_iid: str):
        return answer["outcome"]

    removal = mesh_removal.Removal(open_db, B, _quiet_steps(retire_from=retire_from, notify=told.append), box, clock)

    async def run() -> None:
        await deliver(removal, box, with_x)
        await deliver(removal, box, without_x)
        for _ in range(3):
            clock.t += mesh_removal.RETRY_SECONDS
            await removal.pass_once()
        assert told.count(mesh_removal.topics.COMPUTERS) == 1
        answer["outcome"] = {}
        for _ in range(2):
            clock.t += mesh_removal.SETTLE_SECONDS + 1
            await removal.pass_once()
        assert told.count(mesh_removal.topics.COMPUTERS) == 2
        await removal.stop()

    asyncio.run(run())
