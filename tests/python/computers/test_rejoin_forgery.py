
from __future__ import annotations

from contextlib import closing

import pytest

from tests.python.computers.test_join_commit import JOIN, MAIN, Side, _counts, _join_prov, _main_prov, _pair_over_ssh, world  # noqa: F401
from tests.python.computers.test_join_inproc import _join, _server

# ruff: noqa: E402, F811
from src.core.computers import commit, join_client, store
from src.core.computers.commit import JoinRefused
from src.core.computers.invites import Invites
from src.core.computers.join_client import JoinFailed
from src.core.federation import grants, peer_hosts
from src.core.pack.machines import settings_doc


def test_message_4_key_must_match_the_live_grant(world):
    main, join = world
    _pair_over_ssh(main, join)
    own, existing, kind = join_client._check_rules(join.open_db, JOIN, MAIN, main.key.device_id, True)
    assert (own, existing, kind) == ("gj", "gm", "migrate")
    with pytest.raises(JoinFailed) as bad:
        join_client._check_rules(join.open_db, JOIN, MAIN, join.key.device_id, True)
    assert bad.value.code == "main_mismatch"


@pytest.mark.asyncio
async def test_joiner_writes_refuse_a_migrate_from_another_key_and_touch_nothing(world):
    main, join = world
    _pair_over_ssh(main, join)
    res = await _main_prov(main, join, "migrate")
    forged = main.peer_id(res.grant_id, "air")
    forged = type(forged)(forged.install_id, forged.label, join.public, forged.cert_der, forged.link_fid, forged.grant_id)
    before, doc = _counts(join), join.pack.settings()
    with pytest.raises(JoinRefused):
        await commit.joiner_provisional(join.open_db, join.links, identity=join.identity, own_iid=JOIN, main=forged, own_grant_id="gj",
                                        kind="migrate", settings=res.settings, addresses=["10.0.0.5"], link_port=47110, pack=join.pack)
    assert _counts(join) == before and join.pack.settings() == doc and join.links.started == []


@pytest.mark.asyncio
async def test_failed_rejoin_restores_the_exact_old_document_and_the_ssh_link(world, monkeypatch):
    main, join = world
    _pair_over_ssh(main, join)
    with closing(join.open_db()) as c:
        peer_hosts.set_initiator(c, MAIN, True)
    res = await _main_prov(main, join, "migrate")
    before = join.pack.settings()
    monkeypatch.setattr(peer_hosts, "set_initiator", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError):
        await _join_prov(main, join, res, "migrate")
    monkeypatch.undo()
    assert join.pack.settings() == before and join.links.removed == [MAIN] and join.links.started == [MAIN]


@pytest.mark.asyncio
async def test_sweeper_redials_the_old_ssh_link_after_a_reverted_migrate(world):
    main, join = world
    _pair_over_ssh(main, join)
    with closing(join.open_db()) as c:
        peer_hosts.set_initiator(c, MAIN, True)
    res = await _main_prov(main, join, "migrate")
    await _join_prov(main, join, res, "migrate")
    join.links.started.clear()
    await commit.sweep(join.open_db, identity=join.identity, own_iid=JOIN, pack=join.pack, links=join.links, max_age=0)
    assert join.links.started == [MAIN] and _counts(join)[0] == []


@pytest.mark.asyncio
async def test_rejoin_after_main_lost_its_grant_repoints_the_grant_in_place(world):
    main, join = world
    _pair_over_ssh(main, join)
    with closing(main.open_db()) as c:
        grants.revoke(c, "gm")
        peer_hosts.delete(c, JOIN)
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    out = await _join(main, join, srv.port, mode="code", code=inv.code, require_existing_grant=True)
    assert out.kind == "migrate"
    live = [g for g in _counts(join)[1] if not g.revoked]
    assert len(live) == 1 and live[0].grant_id == "gj" and live[0].remote_grant_id != "gm"


@pytest.mark.asyncio
async def test_expect_fid_must_equal_the_main_that_answered(world):
    main, join = world
    invites = Invites()
    srv = _server(main, invites)
    inv = invites.mint("code")
    await srv.sync()
    with pytest.raises(JoinFailed) as bad:
        await _join(main, join, srv.port, mode="code", code=inv.code, expect_fid=join.key.device_id)
    assert bad.value.code == "main_mismatch" and _counts(join) == ([], [], [])
    out = await _join(main, join, srv.port, mode="code", code=invites.mint("code").code, expect_fid=main.key.device_id)
    assert out.kind == "new"
