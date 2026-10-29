
from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import dataclass

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, peer_link
from src.core.federation.peer_client import PeerRefused, PeerUnreachable, Route
from src.core.federation.peer_link import LinkDown, PeerLink


@dataclass
class Reply:
    status_code: int
    data: dict

    def json(self):
        return self.data


class FakeClient:

    def __init__(self, script):
        self.script = script

    async def request(self, method, path, **_kw):
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return Reply(200, item)


def _link(scripts, states):
    scripts = list(scripts)
    calls = {"establish": 0}

    async def establish():
        calls["establish"] += 1
        return Route("unix", "/x")

    link = PeerLink(peer_install_id="iid", establish=establish,
                    make_client=lambda _r: FakeClient(scripts.pop(0) if len(scripts) > 1 else scripts[0]),
                    on_state=lambda s, p: states.append(s), heartbeat=0.01, delay=lambda _a: 0.01)
    return link, calls


async def _until(predicate, seconds=3.0):
    for _ in range(int(seconds / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


OK = {"install_id": "iid", "protocol": 1}


def test_a_lost_link_reads_disconnected_and_is_redialled():
    async def run():
        states = []
        link, calls = _link([[OK, PeerUnreachable("refused", hard=True)], [OK]], states)
        link.start()
        await _until(lambda: calls["establish"] >= 2 and link.state == peer_link.CONNECTED)
        await link.stop()
        return states

    states = asyncio.run(run())
    assert states.index("connected") < states.index("disconnected") < len(states) - 1
    assert states[-1] == "disconnected"


def test_a_protocol_major_mismatch_is_incompatible():
    async def run():
        link, _ = _link([[{"install_id": "iid", "protocol": 2}]], [])
        link.start()
        await _until(lambda: link.state == peer_link.INCOMPATIBLE)
        await link.stop()

    asyncio.run(run())


def test_a_revoked_grant_reads_unpaired_and_a_changed_install_id_reads_identity_changed():
    async def run(script, state):
        link, _ = _link([script], [])
        link.start()
        await _until(lambda: link.state == state)
        await link.stop()

    asyncio.run(run([PeerRefused("grant_invalid")], peer_link.UNPAIRED))
    asyncio.run(run([{"install_id": "other", "protocol": 1}], peer_link.IDENTITY_CHANGED))


def test_an_establish_that_cannot_dial_stays_disconnected():
    async def run():
        async def establish():
            raise LinkDown("ssh retrying")

        link = PeerLink(peer_install_id="iid", establish=establish, make_client=lambda _r: None,
                        heartbeat=0.01, delay=lambda _a: 0.01)
        link.start()
        await asyncio.sleep(0.05)
        state = link.state
        await link.stop()
        return state

    assert asyncio.run(run()) in (peer_link.DISCONNECTED, peer_link.CONNECTING)


def test_v44_adds_the_host_columns_and_peer_rows_round_trip(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hosts)")}
        assert {"kind", "peer_install_id", "peer_grant_id", "peer_state", "peer_back_kind"} <= cols
        assert conn.execute("SELECT kind FROM hosts WHERE key = 'local'").fetchone()[0] == "local"
        row = peer_hosts.upsert(conn, install_id="AB-12-cd", label="hosta", grant_id="g", fid="f", initiator=True,
                                ssh_target="hosta", peer_port=8000, back_kind="tcp")
        assert row.key == peer_hosts.host_key_for("AB-12-cd") and row.initiator and row.back_kind == "tcp" and row.peer_state == "disconnected"
        peer_hosts.set_state(conn, "AB-12-cd", "connected", 1)
        assert peer_hosts.get(conn, "AB-12-cd").peer_state == "connected"
        assert peer_hosts.upsert(conn, install_id="AB-12-cd", label="hosta2", grant_id="g", fid="f",
                                 initiator=True).label == "hosta2"
        assert peer_hosts.delete(conn, "AB-12-cd") and peer_hosts.list_peers(conn) == []
