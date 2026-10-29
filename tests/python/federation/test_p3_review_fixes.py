
from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing

import pytest

from tests.lifecycle_helpers import add_row

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_events, peer_hosts, peer_http, peer_listing, shadow_rows
from src.core.federation.ddl_peer_sessions import REVERSAL_SQL_V45
from src.core.federation.peer_link import CONNECTED, DISCONNECTED

IID_A = "49759e95-ca80-470e-8314-dc0cfeebc803"


class Reply:
    def __init__(self, data, status=200, raw=None):
        self.data, self.status_code, self.raw = data, status, raw

    def json(self):
        return json.loads(self.raw) if self.raw is not None else self.data


class Owner:
    def __init__(self, tmp_path):
        self.dir = tmp_path / "O"
        self.dir.mkdir()
        ensure_db_migrated(self.dir)
        self.state, self.replies, self.kw = CONNECTED, {}, {}

    def open_db(self):
        return connect(db_path_for(self.dir), create=False)

    def pair(self, install_id=IID_A):
        with closing(self.open_db()) as conn:
            return peer_hosts.upsert(conn, install_id=install_id, label="p", grant_id="g", fid="f", initiator=True)

    def client(self, iid):
        return _Client(self, iid) if self.state == CONNECTED else None

    def links(self):
        owner = self

        class L:
            def client(self, iid):
                return owner.client(iid)

            def state(self, iid):
                return owner.state
        return L()

    async def listing(self, infos=()):
        return await peer_listing.for_caller(list(infos), is_peer=False, open_db=self.open_db, links=self.links())

    def count(self, sql):
        with closing(self.open_db()) as conn:
            return conn.execute(sql).fetchone()[0]


class _Client:
    def __init__(self, owner, iid):
        self.owner, self.iid = owner, iid

    async def request(self, method, path, **kw):
        self.owner.kw = kw
        r = self.owner.replies[self.iid]
        return r() if callable(r) else r


def row(name, uuid, status="working", wd="/work", iid=IID_A, **extra):
    base = {"session": {"id": f"ses_{name}", "working_dir": wd, "status": "running"},
            "tmux_session": name, "session_row_id": 1, "activity_status": status, "unread": False,
            "startup_gate": "ready", "host_key": "local", "origin_install_id": iid, "session_uuid": uuid}
    base.update(extra)
    return base


@pytest.fixture
def owner(tmp_path):
    peer_listing.reset()
    return Owner(tmp_path)


def test_h1_deep_json_never_breaks_the_owner_listing(owner):
    owner.pair()
    owner.replies[IID_A] = Reply(None, raw="[" * 60000)
    assert asyncio.run(owner.listing(["local-row"])) == ["local-row"]


def test_h1_one_broken_peer_costs_only_its_own_rows(owner):
    other = "8a2e38e6-515b-4f60-8f04-7a270ab6bf05"
    owner.pair()
    owner.pair(other)
    owner.replies[IID_A] = Reply(None, raw="[" * 60000)
    owner.replies[other] = Reply([row("web", "u9", iid=other)])
    rows = asyncio.run(owner.listing())
    assert [r.tmux_session for r in rows] == ["web"]


def test_h2_the_listing_asks_for_its_own_larger_cap_and_the_default_stays_small(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    assert owner.kw.get("max_body") == peer_http.MAX_LISTING_BODY > 300 * 1800
    assert peer_http.MAX_BODY == 64 * 1024


def test_h2_a_reply_past_the_small_cap_reads_only_with_the_larger_one():
    async def go():
        payload = b"[" + b",".join([b'"x' + b"y" * 500 + b'"'] * 200) + b"]"

        async def handle(r, w):
            await r.readuntil(b"\r\n\r\n")
            w.write(b"HTTP/1.1 200 OK\r\ncontent-length: %d\r\n\r\n" % len(payload) + payload)
            await w.drain()
            w.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            for cap, ok in ((peer_http.MAX_BODY, False), (peer_http.MAX_LISTING_BODY, True)):
                reader, writer = await peer_http.open_connection("tcp", port)
                try:
                    if ok:
                        assert len((await peer_http.exchange(reader, writer, "GET", "/x", max_body=cap)).json()) == 200
                    else:
                        with pytest.raises(peer_http.ReplyTooLarge):
                            await peer_http.exchange(reader, writer, "GET", "/x", max_body=cap)
                finally:
                    writer.close()
        finally:
            server.close()
    assert len(b"y" * 500 * 200) > peer_http.MAX_BODY
    asyncio.run(go())


def test_h3_a_snapshot_nobody_refreshed_reads_disconnected_and_unknown(owner, monkeypatch):
    monkeypatch.setattr(peer_listing, "STALE_SECONDS", 0.05)
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1", status="working")])
    asyncio.run(owner.listing())
    owner.replies[IID_A] = Reply(None, status=500)
    time.sleep(peer_listing.FRESH_SECONDS + 0.1)
    r = asyncio.run(owner.listing())[0]
    assert r.activity_status == "unknown" and r.host_state == "disconnected"


def test_h4_concurrent_callers_share_one_failed_fetch(owner, monkeypatch):
    owner.pair()
    monkeypatch.setattr(peer_listing, "DEADLINE_SECONDS", 0.3)
    calls = []

    class Slow:
        async def request(self, *a, **k):
            calls.append(1)
            await asyncio.sleep(10)

    owner.client = lambda iid: Slow()

    async def many():
        t0 = time.monotonic()
        await asyncio.gather(*(owner.listing() for _ in range(8)))
        return time.monotonic() - t0

    took = asyncio.run(many())
    assert took < 3 * 0.3 and len(calls) == 1, (took, len(calls))


def test_m1_an_unreadable_row_stops_no_shadow_row(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    owner.replies[IID_A] = Reply([row("api", None)])
    time.sleep(peer_listing.FRESH_SECONDS + 0.1)
    asyncio.run(owner.listing())
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer' AND lifecycle='running'") == 1


def test_m2_a_disconnected_row_paints_nothing_it_cannot_vouch_for(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1", status="idle", startup_gate="awaiting_startup_prompt",
                                      unread=True, subagents_running=3, timers_live=2, background_open=1)])
    asyncio.run(owner.listing())
    owner.state = DISCONNECTED
    r = asyncio.run(owner.listing())[0]
    assert (r.activity_status, r.host_state, r.startup_gate, r.unread) == ("unknown", "disconnected", "unknown", False)
    assert r.subagents_running is None and r.timers_live is None and r.background_open is None and r.stats is None


def test_m3_a_churning_peer_is_capped_and_pruned(owner, monkeypatch):
    monkeypatch.setattr(shadow_rows, "PRUNE_GRACE_SECONDS", -60)
    owner.pair()
    for i in range(5):
        owner.replies[IID_A] = Reply([row(f"s{i}_{j}", f"u{i}_{j}", wd=f"/w/{i}/{j}") for j in range(200)])
        asyncio.run(peer_listing.peer_rows(owner.open_db, owner.links(), force=True))
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer'") <= 400
    assert owner.count("SELECT COUNT(*) FROM projects WHERE root LIKE 'peer://%'") <= 400
    owner.replies[IID_A] = Reply([row(f"b{j}", f"bu{j}", wd=f"/b/{j}") for j in range(shadow_rows.MAX_ROWS + 100)])
    asyncio.run(peer_listing.peer_rows(owner.open_db, owner.links(), force=True))
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer' AND tmux_name LIKE 'b%'") == shadow_rows.MAX_ROWS


def test_m3_a_peers_stopped_rows_stay_out_of_recent():
    import inspect
    from src.api import session_recent_routes
    assert 'origin") != "peer"' in inspect.getsource(session_recent_routes)


def test_l1_unpair_removes_the_shadow_rows_projects_and_snapshot(owner):
    peer = owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    with closing(owner.open_db()) as conn:
        shadow_rows.remove_peer(conn, peer.key)
    peer_listing.forget(IID_A)
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer'") == 0
    assert owner.count("SELECT COUNT(*) FROM projects WHERE root LIKE 'peer://%'") == 0
    assert owner.count("SELECT COUNT(*) FROM peer_sessions") == 0 and IID_A not in peer_listing._SNAPSHOTS


def test_l1_the_acceptor_drops_its_peer_hosts_row_too(owner):
    from src.api.federation_routes import _drop_peer
    peer = owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    with closing(owner.open_db()) as conn:
        _drop_peer(conn, "g", IID_A)
        assert peer_hosts.get(conn, IID_A) is None
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer'") == 0 and peer.key


def test_l2_cold_rows_are_never_up_and_carry_no_stats(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    peer_listing.reset()
    owner.replies[IID_A] = Reply(None, status=500)
    r = asyncio.run(owner.listing())[0]
    assert r.host_state == "disconnected" and r.stats is None and r.activity_status == "unknown"


@pytest.mark.parametrize("wd", ["relative/dir", "/a/../b", "/a//b", "", "/" + "x" * 2000])
def test_l3_a_folder_that_is_not_absolute_and_normalized_is_refused(owner, wd):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1", wd=wd)])
    assert asyncio.run(owner.listing()) == []
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer'") == 0


def test_l5_undoing_v45_removes_the_shadow_rows_and_peer_projects(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    asyncio.run(owner.listing())
    with closing(owner.open_db()) as conn:
        for statement in REVERSAL_SQL_V45:
            conn.execute(statement)
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer'") == 0
    assert owner.count("SELECT COUNT(*) FROM projects WHERE root LIKE 'peer://%'") == 0


def test_l6_an_unchanged_row_is_not_written_again(owner, monkeypatch):
    owner.pair()
    owner.replies[IID_A] = Reply([row("api", "u1")])
    stamps = iter(f"2030-01-01T00:00:0{i}Z" for i in range(9))
    monkeypatch.setattr(shadow_rows, "utc_now", lambda: next(stamps))
    asyncio.run(peer_listing.peer_rows(owner.open_db, owner.links(), force=True))
    first = owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer' AND updated_at = '2030-01-01T00:00:00Z'")
    asyncio.run(peer_listing.peer_rows(owner.open_db, owner.links(), force=True))
    assert first == 1
    assert owner.count("SELECT COUNT(*) FROM sessions WHERE origin='peer' AND updated_at = '2030-01-01T00:00:00Z'") == 1


def test_l6_a_peer_reserving_our_own_session_is_refused(owner):
    owner.pair()
    with closing(owner.open_db()) as conn:
        add_row(conn, uuid="our-own-uuid", name="cloude_mine", epoch=1000)
    owner.replies[IID_A] = Reply([row("mine", "our-own-uuid"), row("theirs", "u2")])
    assert [r.tmux_session for r in asyncio.run(owner.listing())] == ["theirs"]


def test_l6_a_flood_of_light_changes_is_one_re_read_notice(owner):
    owner.pair()
    owner.replies[IID_A] = Reply([row(f"s{i}", f"u{i}", status="idle") for i in range(40)])
    before = peer_events._lights(asyncio.run(owner.listing()))
    owner.replies[IID_A] = Reply([row(f"s{i}", f"u{i}", status="working") for i in range(40)])
    peer_listing.reset()
    frames = peer_events.diff(before, asyncio.run(owner.listing()), last_sent={}, clock=100.0)
    assert len(frames) == 1


def test_the_served_row_carries_none_of_what_the_importer_replaces():
    from src.core.federation import peer_serve
    from src.models import SessionInfo

    info = SessionInfo.model_validate({
        "session": {"id": "ses_1", "pty_pid": 4242, "working_dir": "/w"}, "tmux_session": "n",
        "parent_session_id": 5, "project_id": 9, "project_name": "p"})
    row = peer_serve._slim(info, "iid", "u-1")
    assert (row.session.pty_pid, row.parent_session_id, row.project_id, row.project_name) == (None, None, None, None)
    assert row.session.working_dir == "/w" and row.origin_install_id == "iid" and row.session_uuid == "u-1"
    assert info.session.pty_pid == 4242
