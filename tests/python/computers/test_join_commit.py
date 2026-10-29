
from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import closing
from pathlib import Path
from typing import List

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import setup_state
from src.core.computers import commit, membership, store
from src.core.computers.commit import JoinRefused, PeerId
from src.core.computers.tls_identity import ensure_link_identity
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import fed_key, grants, peer_hosts
from src.core.pack.machines import settings_doc
from src.core.pack.machines.config_state import ConfigState
from src.core.relay_identity.device_key import DeviceKey

MAIN, JOIN = "main-install-aaaa", "join-install-bbbb"


class Pack:

    def __init__(self, path: Path, default_master: str, iid: str) -> None:
        self.state, self.default_master, self.iid = ConfigState(lambda: path), default_master, iid

    def settings(self):
        return self.state.stored_settings() or settings_doc.default_doc(self.default_master)

    def signature(self):
        return self.state.settings_signature()

    def mint(self, changes, base=None):
        doc = settings_doc.edited(base or self.settings(), changes, self.iid)
        self.state.save_settings(doc)
        return doc

    def adopt(self, doc, signature=None) -> bool:
        return self.state.save_settings(doc, signature)

    def save_settings(self, doc) -> bool:
        return self.state.save_settings(doc)


class FakeLinks:
    def __init__(self) -> None:
        self.started: List[str] = []
        self.removed: List[str] = []

    async def start_initiator(self, row) -> None:
        self.started.append(row.peer_install_id)

    async def remove(self, iid: str) -> None:
        self.removed.append(iid)


class FakeListener:
    def __init__(self, fail: bool = False) -> None:
        self.sets: List[List[str]] = []
        self.fail = fail

    async def set_members(self, members) -> str:
        if self.fail:
            raise OSError("bind failed")
        self.sets.append([m.peer_install_id for m in members])
        return "listening"


class Side:

    def __init__(self, root: Path, name: str, iid: str, seed: int, default_master: str) -> None:
        self.iid, self.dir = iid, root / name
        self.dir.mkdir(mode=0o700)
        ensure_db_migrated(self.dir)
        self.key = DeviceKey.from_seed(bytes([seed]) * 32)
        self.public = fed_key.public_key_b64(self.key)
        self.identity = ensure_link_identity(self.key, iid, self.dir)
        self.config = self.dir / "config.json"
        self.config.write_text("{}")
        self.pack = Pack(self.config, default_master, iid)
        self.links, self.listener = FakeLinks(), FakeListener()

    def open_db(self):
        return connect(db_path_for(self.dir), create=False)

    def peer_id(self, grant_id: str, label: str) -> PeerId:
        return PeerId(self.iid, label, self.public, self.identity.cert.der, self.identity.cert.link_fid, grant_id)

    def query(self, fn):
        with closing(self.open_db()) as conn:
            return fn(conn)


@pytest.fixture()
def world():
    root = Path(tempfile.mkdtemp(prefix="jc"))
    store.CACHE.replace([])
    main = Side(root, "main", MAIN, 1, MAIN)
    join = Side(root, "join", JOIN, 2, JOIN)
    yield main, join
    import shutil

    shutil.rmtree(root, ignore_errors=True)


async def _main_prov(main: Side, join: Side, kind: str, grant: str = "gj", **kw):
    return await commit.main_provisional(main.open_db, main.listener, identity=main.identity, own_iid=MAIN,
                                         joiner=join.peer_id(grant, "hosta"), kind=kind, pack=main.pack, **kw)


async def _join_prov(main: Side, join: Side, res, kind: str, own_grant: str = "gj"):
    await commit.joiner_provisional(join.open_db, join.links, identity=join.identity, own_iid=JOIN,
                                    main=main.peer_id(res.grant_id, "air"), own_grant_id=own_grant, kind=kind,
                                    settings=res.settings, addresses=["192.0.2.13"], link_port=47110, pack=join.pack)


def _counts(side: Side):
    return side.query(lambda c: (store.list_rows(c), grants.list_grants(c), peer_hosts.list_peers(c)))


def _pair_over_ssh(main: Side, join: Side) -> None:
    with closing(main.open_db()) as c:
        grants.create_grant(c, peer_install_id=JOIN, public_key=join.public, label="hosta", remote_grant_id="gj", grant_id="gm")
        peer_hosts.upsert(c, install_id=JOIN, label="hosta", grant_id="gj", fid="f", initiator=True, ssh_target="acme@hosta", ssh_port=22)
    with closing(join.open_db()) as c:
        grants.create_grant(c, peer_install_id=MAIN, public_key=main.public, label="air", remote_grant_id="gm", grant_id="gj")
        peer_hosts.upsert(c, install_id=MAIN, label="air", grant_id="gm", fid="f", initiator=False)


@pytest.mark.asyncio
async def test_new_member_provisional_then_final_on_both_sides(world):
    main, join = world
    (join.dir / setup_state.PAIRED_SENTINEL_NAME).write_text("x")
    res = await _main_prov(main, join, "new")
    rows, gr, hosts = _counts(main)
    assert [(r.peer_install_id, r.role, r.join_kind, r.provisional, r.inbound_control) for r in rows] == [(JOIN, "member", "new", True, 1)]
    assert [(g.grant_id, g.remote_grant_id) for g in gr] == [(res.grant_id, "gj")] and not hosts[0].initiator and hosts[0].peer_grant_id == "gj"
    assert main.listener.sets == [[JOIN]]
    await _join_prov(main, join, res, "new")
    rows, gr, hosts = _counts(join)
    assert (rows[0].role, rows[0].addresses, rows[0].link_port, rows[0].provisional) == ("main", ("192.0.2.13",), 47110, True)
    assert hosts[0].initiator and hosts[0].peer_grant_id == res.grant_id and gr[0].grant_id == "gj" and join.links.started == [MAIN]
    assert not setup_state.joined_marker_path(join.config).exists()
    assert (join.dir / setup_state.PAIRED_SENTINEL_NAME).exists()

    assert await commit.main_final(main.open_db, main.links, JOIN) is True
    assert main.links.removed == []
    revoked: List[int] = []

    async def revoke_all() -> int:
        revoked.append(1)
        return 3

    membership._rebind_requested = False
    assert await commit.joiner_final(join.open_db, MAIN, config_path=join.config, revoke_refresh_tokens=revoke_all) is True
    marker = setup_state.joined_marker_path(join.config)
    assert stat.S_IMODE(os.stat(marker).st_mode) == 0o600 and json.loads(marker.read_text())["main"] == MAIN
    assert not (join.dir / setup_state.PAIRED_SENTINEL_NAME).exists() and revoked and membership.rebind_requested()
    assert not _counts(main)[0][0].provisional and not _counts(join)[0][0].provisional
    assert await commit.joiner_final(join.open_db, MAIN, config_path=join.config, revoke_refresh_tokens=revoke_all) is False
    assert await commit.main_final(main.open_db, main.links, JOIN) is False


@pytest.mark.asyncio
async def test_master_pin_counter_is_bumped_and_equal_on_both_sides(world):
    main, join = world
    main.pack.save_settings(settings_doc.PackSettings(master_install_id="boss-install", rev=(5, "boss-install")))
    res = await _main_prov(main, join, "new")
    await _join_prov(main, join, res, "new")
    held_main, held_join = main.pack.settings(), join.pack.settings()
    assert held_main.master_install_id == "boss-install" and held_main.rev == (6, MAIN)
    assert held_join == held_main and res.settings == held_main.model_dump(mode="json")
    lone = Side(Path(tempfile.mkdtemp(prefix="jl")), "m2", "lone-install-cccc", 3, "lone-install-cccc")
    r2 = await commit.main_provisional(lone.open_db, lone.listener, identity=lone.identity, own_iid="lone-install-cccc",
                                       joiner=join.peer_id("gj", "t"), kind="new", pack=lone.pack)
    assert r2.settings["master_install_id"] == "lone-install-cccc" and r2.settings["rev"] == [1, "lone-install-cccc"]


@pytest.mark.asyncio
async def test_migrate_keeps_main_ssh_link_until_final_then_flips(world):
    main, join = world
    _pair_over_ssh(main, join)
    res = await _main_prov(main, join, "migrate")
    rows, gr, hosts = _counts(main)
    assert res.grant_id == "gm" and len(gr) == 1 and rows[0].join_kind == "migrate" and rows[0].prev_initiator == 1
    assert hosts[0].initiator is True and hosts[0].ssh_target == "acme@hosta" and main.links.removed == []
    await _join_prov(main, join, res, "migrate")
    _rows, jgr, jhosts = _counts(join)
    assert jhosts[0].initiator is True and len(jgr) == 1 and join.links.started == [MAIN]
    assert _counts(join)[0][0].prev_initiator == 0
    await commit.main_final(main.open_db, main.links, JOIN)
    hosts = _counts(main)[2]
    assert main.links.removed == [JOIN] and hosts[0].initiator is False and hosts[0].ssh_target == "acme@hosta"


@pytest.mark.asyncio
async def test_migrate_that_never_links_reverts_to_the_same_grant_and_hosts_rows(world):
    main, join = world
    _pair_over_ssh(main, join)
    before_main, before_join = _counts(main)[1:], _counts(join)[1:]
    res = await _main_prov(main, join, "migrate")
    await _join_prov(main, join, res, "migrate")
    for side in (main, join):
        await commit.sweep(side.open_db, identity=side.identity, own_iid=side.iid, pack=side.pack, links=side.links,
                           listener=side.listener, max_age=0)
    assert _counts(main)[0] == [] and _counts(join)[0] == []
    assert _counts(main)[1:] == before_main and _counts(join)[1:] == before_join
    assert join.links.removed == [MAIN] and main.listener.sets[-1] == []
    assert store.CACHE.rows() == []


@pytest.mark.asyncio
async def test_new_that_never_links_is_removed_and_joiner_is_its_own_master(world):
    main, join = world
    res = await _main_prov(main, join, "new")
    await _join_prov(main, join, res, "new")
    assert join.pack.settings().master_install_id == MAIN
    assert await commit.sweep(main.open_db, identity=main.identity, own_iid=MAIN, pack=main.pack, links=main.links,
                              listener=main.listener, max_age=3600) == []
    for side in (main, join):
        assert await commit.sweep(side.open_db, identity=side.identity, own_iid=side.iid, pack=side.pack, links=side.links,
                                  listener=side.listener, max_age=0) != []
        rows, gr, hosts = _counts(side)
        assert rows == [] and hosts == [] and all(g.revoked for g in gr)
    assert join.pack.settings().master_install_id == JOIN and join.pack.settings().rev[0] > 1


@pytest.mark.asyncio
async def test_compensator_leaves_no_rows_after_an_injected_failure(world, monkeypatch):
    main, join = world
    main.listener.fail = True
    with pytest.raises(OSError):
        await _main_prov(main, join, "new")
    assert _counts(main) == ([], [], []) and store.CACHE.rows() == []
    main.listener.fail = False
    real = peer_hosts.upsert

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(peer_hosts, "upsert", boom)
    with pytest.raises(RuntimeError):
        await _main_prov(main, join, "new")
    assert _counts(main) == ([], [], []) and store.CACHE.rows() == []
    res = await _main_prov_ok(main, join, real, monkeypatch)
    monkeypatch.setattr(peer_hosts, "upsert", boom)
    with pytest.raises(RuntimeError):
        await _join_prov(main, join, res, "new")
    rows, gr, hosts = _counts(join)
    assert rows == [] and gr == [] and hosts == [] and join.links.removed == [MAIN]
    assert join.pack.settings().master_install_id == JOIN


async def _main_prov_ok(main, join, real, monkeypatch):
    monkeypatch.setattr(peer_hosts, "upsert", real)
    return await _main_prov(main, join, "new")


@pytest.mark.asyncio
async def test_refusals_write_nothing(world):
    main, join = world
    bad = PeerId(JOIN, "hosta", join.public, b"\x30\x03junk", "x" * 26, "gj")
    with pytest.raises(JoinRefused):
        await commit.main_provisional(main.open_db, main.listener, identity=main.identity, own_iid=MAIN, joiner=bad, kind="new", pack=main.pack)
    assert _counts(main) == ([], [], []) and main.listener.sets == []
    with closing(main.open_db()) as c:
        assert commit.classify_join(c, own_iid=MAIN, own_link_fid=main.identity.cert.link_fid, joiner=join.peer_id("gj", "t")) == "new"
        with pytest.raises(JoinRefused):
            commit.classify_join(c, own_iid=MAIN, own_link_fid=main.identity.cert.link_fid, joiner=main.peer_id("g", "t"))
        grants.create_grant(c, peer_install_id=JOIN, public_key=main.public, label="x", grant_id="old")
        with pytest.raises(JoinRefused) as info:
            commit.classify_join(c, own_iid=MAIN, own_link_fid=main.identity.cert.link_fid, joiner=join.peer_id("gj", "t"))
        assert info.value.code == "peer_identity_changed"
