
from __future__ import annotations

from contextlib import closing

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

from src.api import hosts_routes
from src.core.argent.pair_sync import PairSync
from src.core.computers import join_client, join_proto, join_server
from src.core.computers.commit import JoinRefused
from src.core.computers.join_client import JoinFailed
from src.core.db import connect
from src.core.federation import peer_hosts
from src.core.hosts import store
from src.core.pack.machines import capabilities
from src.core.pack.relay import member_reach

STAR, MESH = "iid-star-0001", "iid-mesh-0002"


def _old_overlay(conn, hosts):
    from dataclasses import replace

    from src.core.pack.machines import runtime

    peers = {p.key: p for p in peer_hosts.list_peers(conn)} if any(h.kind == "peer" for h in hosts) else {}
    out = []
    for host in hosts:
        peer = peers.get(host.key) if host.kind == "peer" else None
        if peer is None:
            out.append(host)
        elif peer.peer_state != "connected":
            out.append(replace(host, enabled=False, probe_state="refused", probe_detail=hosts_routes.PEER_NOT_CONNECTED))
        elif runtime.peer_restriction(peer.peer_install_id, "may_host_agents") is False:
            out.append(replace(host, enabled=False, probe_state="refused", probe_detail=hosts_routes.PEER_REFUSES_HOSTING))
        else:
            out.append(replace(host, enabled=True, probe_state="ok", probe_detail=None))
    return out


def test_mesh_screens_9c1(monkeypatch, tmp_path):
    db = migrated(tmp_path / "state")
    with closing(connect(db, create=False)) as conn:
        store.create_host(conn, label="box", ssh_target="box.lan")
        peer_hosts.upsert(conn, install_id=STAR, label="star", grant_id="gs", fid="fs", initiator=True)
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
        peer_hosts.upsert_mesh(conn, install_id=MESH, label="member", grant_id="gm", fid="fm")
        rows = store.list_hosts(conn)
        mesh_key = next(h.key for h in rows if h.kind == "peer" and h.key != next(p.key for p in peer_hosts.list_peers(conn)))
        on = {h.key: h for h in hosts_routes.overlay_peers(conn, rows)}
        old = {h.key: h for h in _old_overlay(conn, rows)}
        assert on[mesh_key].computer_install_id == MESH and on[mesh_key].enabled is False
        assert all(on[k] == old[k] for k in on if k != mesh_key)
        assert store.get_host(conn, mesh_key).computer_install_id is None
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
        assert hosts_routes.overlay_peers(conn, rows) == _old_overlay(conn, rows)

    ps = PairSync.__new__(PairSync)
    ps._listing = lambda: [(STAR, "", "connected", []), ("iid-x", "named", "connected", [])]
    from src.core.pack.machines import roster_v2
    from tests.python.pack.test_roster import _inputs
    from tests.python.pack.test_settings_signing import IDS

    signed = roster_v2.plan_v2(None, _inputs(("a", "b", "c"), b={"label": "signed laptop"}), alpha=IDS["a"])
    MESH_ID = IDS["b"]
    monkeypatch.setattr(member_reach, "held_v2", lambda: signed)
    assert ps._label_of(STAR) == "" and ps._label_of("iid-x") == "named"
    assert ps._label_of(MESH_ID) == "signed laptop" and ps._label_of("iid-none") == "iid-none"
    monkeypatch.setattr(member_reach, "held_v2", lambda: None)
    assert ps._label_of(MESH) == MESH

    full = JoinRefused("pack_full", "full")
    assert join_server.refusal_code(full) == "refused"
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert join_server.refusal_code(full) == "pack_full"
    assert join_server.refusal_code(JoinRefused("refused", "x")) == "refused"
    assert join_proto.error("pack_full")["code"] == "pack_full"
    with pytest.raises(JoinFailed) as err:
        join_client._error_of({"t": "error", "code": "pack_full"})
    assert err.value.code == "pack_full"
