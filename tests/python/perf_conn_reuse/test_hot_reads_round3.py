
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Coroutine, Iterator

import pytest
from starlette.concurrency import run_in_threadpool

import src.config  # noqa: F401
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_reuse.change_cache import HOT_READS
from tests.lifecycle_helpers import add_row
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 12


@pytest.fixture
def run() -> Iterator[Callable[[Coroutine], object]]:
    event_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=event_loop.run_forever, name="test-loop", daemon=True)
    thread.start()
    started = threading.Event()

    async def root() -> None:
        await run_in_threadpool(started.set)
        await asyncio.Event().wait()

    asyncio.run_coroutine_threadsafe(root(), event_loop)
    assert started.wait(timeout=10)
    yield lambda coro: asyncio.run_coroutine_threadsafe(coro, event_loop).result(timeout=30)
    event_loop.call_soon_threadsafe(event_loop.stop)
    thread.join(timeout=5)
    event_loop.close()


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    d = tmp_path / "state"
    d.mkdir()
    assert ensure_db_migrated(d, 4, "0.0.0").status == "ok"
    from src.config import settings

    monkeypatch.setattr(settings, "state_dir_override", str(d))
    HOT_READS.clear()
    yield d
    HOT_READS.clear()


@pytest.fixture
def open_db(state_dir: Path) -> Callable[[], sqlite3.Connection]:

    from src.core.db_reuse.core_read import lend_pooled_or_raise

    def opener() -> sqlite3.Connection:
        return lend_pooled_or_raise(db_path_for(state_dir))

    return opener


def write(state_dir: Path, work: Callable[[sqlite3.Connection], None]) -> None:
    with closing(connect(db_path_for(state_dir))) as conn, conn:
        work(conn)


def touch(state_dir: Path) -> None:
    write(state_dir, lambda conn: conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('churn', datetime('now'))"))


def idle_cost(monkeypatch, read: Callable[[], object]) -> int:
    for _ in range(3):
        read()
    opened = count_connects(monkeypatch)
    for _ in range(N):
        read()
    return opens_of(opened, "carnivore.db")


def churn_cost(monkeypatch, state_dir: Path, read: Callable[[], object]) -> int:
    for _ in range(3):
        read()
    opened = count_connects(monkeypatch)
    cost = 0
    for _ in range(N):
        touch(state_dir)
        mark = opens_of(opened, "carnivore.db")
        read()
        cost += opens_of(opened, "carnivore.db") - mark
    return cost


def test_stats_feed_pinned_peers_open_nothing_and_see_a_new_peer(state_dir, open_db, monkeypatch):
    from src.core.federation import peer_hosts
    from src.core.stats_feed import peers

    assert idle_cost(monkeypatch, lambda: peers._pinned(open_db)) == 0
    assert churn_cost(monkeypatch, state_dir, lambda: peers._pinned(open_db)) == 0
    assert peers._pinned(open_db) == {}
    write(state_dir, lambda conn: peer_hosts.upsert(conn, install_id="iid-b", label="B", grant_id="g", fid="f", initiator=True))
    seen = peers._pinned(open_db)
    assert [p.label for p in seen.values()] == ["B"]
    seen.clear()
    assert len(peers._pinned(open_db)) == 1


def test_spawn_queue_count_opens_nothing_and_sees_a_new_spawn(state_dir, open_db, monkeypatch):
    from src.core.pack.placement import maintain, queue

    assert idle_cost(monkeypatch, lambda: maintain._count_waiting(open_db)) == 0
    assert churn_cost(monkeypatch, state_dir, lambda: maintain._count_waiting(open_db)) == 0
    assert maintain._count_waiting(open_db) == 0
    write(state_dir, lambda conn: queue.enqueue(conn, {"name": "x"}, "full"))
    assert maintain._count_waiting(open_db) == 1


def test_cplug_session_uuids_open_nothing_under_churn_and_see_a_new_row(state_dir, open_db, monkeypatch):
    from src.api import peer_auth
    from src.cplugs.host import session_uuid_reads

    monkeypatch.setattr(peer_auth, "open_db", open_db)
    holder: dict = {}
    write(state_dir, lambda conn: holder.update(row=add_row(conn, uuid="u-one", name="cloude_a", epoch=1)))
    row = holder["row"]
    assert idle_cost(monkeypatch, lambda: session_uuid_reads.session_uuids([row])) == 0
    assert churn_cost(monkeypatch, state_dir, lambda: session_uuid_reads.session_uuids([row])) == 0
    write(state_dir, lambda conn: holder.update(two=add_row(conn, uuid="u-two", name="cloude_b", epoch=2)))
    assert session_uuid_reads.session_uuids([holder["two"]]) == {holder["two"]: "u-two"}


def test_owned_instances_open_nothing_under_churn_and_see_an_adoption(state_dir, monkeypatch):
    from src.core.live_ports import LiveSessionRecordStore, LiveSettings
    from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger

    store = LiveSessionRecordStore(settings_reader=LiveSettings())
    ledger = OwnedTmuxLedger(metadata_path=lambda: state_dir / "meta.json", records=store, socket_name=lambda: "cloude")
    assert idle_cost(monkeypatch, ledger.instances_from_db) == 0
    assert churn_cost(monkeypatch, state_dir, ledger.instances_from_db) == 0
    before = ledger.instances_from_db()
    write(state_dir, lambda conn: add_row(conn, uuid="u-own", name="cloude_own", epoch=77, origin="created"))
    assert ledger.instances_from_db() - before == {("cloude_own", 77)}


def test_stored_session_records_open_nothing_and_see_a_new_row(state_dir, monkeypatch, run):
    from src.api.session_records_routes import stored_record_rows

    def read() -> list:
        return run(stored_record_rows(SimpleNamespace()))

    assert idle_cost(monkeypatch, read) == 0
    assert churn_cost(monkeypatch, state_dir, read) == 0
    assert read() == []
    write(state_dir, lambda conn: add_row(conn, uuid="u-rec", name="cloude_rec", epoch=5))
    rows = read()
    assert [r.session_uuid for r in rows] == ["u-rec"]
    rows[0].session_uuid = "edited"
    assert read()[0].session_uuid == "u-rec"


def test_recent_sessions_open_nothing_and_see_a_stopped_row(state_dir, monkeypatch, run):
    from src.api.session_recent_routes import recent_response

    app_state = SimpleNamespace(services=SimpleNamespace(probe_health=SimpleNamespace(health=SimpleNamespace(ok=True, reason=None))))

    def read() -> list:
        return run(recent_response(app_state)).sessions

    assert idle_cost(monkeypatch, read) == 0
    assert churn_cost(monkeypatch, state_dir, read) == 0
    assert read() == []
    write(state_dir, lambda conn: add_row(conn, uuid="u-old", name="cloude_old", epoch=9, lifecycle="stopped"))
    assert [r.session_uuid for r in read()] == ["u-old"]


def test_computers_view_rows_open_nothing_and_see_a_new_peer(state_dir, open_db, monkeypatch):
    from src.core.computers import view
    from src.core.federation import peer_hosts

    rt = SimpleNamespace(open_db=open_db, listener=None, dialer=None, link_state="stopped", invites=None, fed_key=None,
                         iid="me", label="Me", link_port=0, join_server=None, addresses=[], member_listener=None)
    links = SimpleNamespace(state=lambda iid: "disconnected")
    assert idle_cost(monkeypatch, lambda: view.build_view(rt, links)) == 0
    assert churn_cost(monkeypatch, state_dir, lambda: view.build_view(rt, links)) == 0
    assert view.build_view(rt, links)["computers"] == []
    write(state_dir, lambda conn: peer_hosts.upsert(conn, install_id="iid-b", label="B", grant_id="g", fid="f", initiator=True))
    assert [c["label"] for c in view.build_view(rt, links)["computers"]] == ["B"]


def test_relay_setting_opens_nothing_and_sees_a_new_target(state_dir, open_db, monkeypatch):
    from src.api import pack_relay_routes as routes
    from src.core.pack.relay import runtime as relay_runtime, targets

    monkeypatch.setattr(routes, "open_db", open_db)
    monkeypatch.setattr(routes, "_claude_account_ids", lambda: ["acct"])
    monkeypatch.setattr(relay_runtime, "candidate_ids", lambda: [])
    assert idle_cost(monkeypatch, routes._read) == 0
    assert churn_cost(monkeypatch, state_dir, routes._read) == 0
    write(state_dir, lambda conn: targets.set_machines(conn, "acct", ["iid-b"], "iid-a"))
    assert [e["machine"] for e in routes._read()["accounts"]["acct"]] == ["iid-b"]


def test_default_master_opens_nothing_and_sees_a_new_pairing(state_dir, open_db, monkeypatch):
    from src.core.federation import grants, peer_hosts
    from src.core.pack.machines import runtime

    def read() -> str:
        return runtime.stored_default_master(open_db, "me")

    assert idle_cost(monkeypatch, read) == 0
    assert churn_cost(monkeypatch, state_dir, read) == 0
    assert read() == "me"

    def pair(conn: sqlite3.Connection) -> None:
        peer_hosts.upsert(conn, install_id="iid-b", label="B", grant_id="g", fid="f", initiator=False)
        grants.create_grant(conn, peer_install_id="iid-b", public_key="A" * 43, label="B")

    write(state_dir, pair)
    assert read() == "iid-b"


def test_relay_setting_keeps_an_account_switched_off_with_no_machines_off(state_dir, open_db, monkeypatch):
    from src.api import pack_relay_routes as routes
    from src.core.pack.relay import runtime as relay_runtime, targets

    monkeypatch.setattr(routes, "open_db", open_db)
    monkeypatch.setattr(routes, "_claude_account_ids", lambda: ["acct"])
    monkeypatch.setattr(relay_runtime, "candidate_ids", lambda: ["iid-b"])
    assert [e["machine"] for e in routes._read()["accounts"]["acct"]] == ["iid-b"]
    write(state_dir, lambda conn: targets.set_machines(conn, "acct", [], "iid-a"))
    seen = routes._read()
    assert seen["default_on"] == []
    assert seen["accounts"].get("acct", []) == []


def test_durable_keys_maps_a_live_row_to_its_stored_uuid_and_an_unstored_one_to_itself(state_dir, open_db, monkeypatch, run):
    from src.api import peer_auth
    from src.cplugs.host.capabilities import Sessions

    monkeypatch.setattr(peer_auth, "open_db", open_db)
    holder: dict = {}
    write(state_dir, lambda conn: holder.update(row=add_row(conn, uuid="u-keyed", name="cloude_k", epoch=3)))
    stored = SimpleNamespace(session=SimpleNamespace(id="ses_stored"), session_row_id=holder["row"])
    unstored = SimpleNamespace(session=SimpleNamespace(id="ses_unstored"), session_row_id=None)

    async def infos() -> list:
        return [stored, unstored]

    keys = run(Sessions(infos).durable_keys())
    assert keys == {"ses_stored": "u-keyed", "ses_unstored": "ses_unstored"}
