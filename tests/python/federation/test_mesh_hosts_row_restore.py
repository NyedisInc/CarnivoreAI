
from __future__ import annotations

import asyncio
import shutil
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from src.core.computers import mesh  # noqa: E402
from src.core.computers.tls_identity import ensure_link_identity  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import mesh_peers, peer_hosts  # noqa: E402
from src.core.hosts import store as hosts_store  # noqa: E402
from src.core.pack.machines import capabilities, roster_doc, roster_v2  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, V2_CAPS, _pair, _wait, root  # noqa: E402,F401,F811
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.python.pack.test_settings_signing import IDS  # noqa: E402


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)


def _db(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    return lambda: connect(db_path_for(tmp_path), create=False)


def _list(only=("a", "b", "c"), links=None):
    d = Path(tempfile.mkdtemp(prefix="mrr"))
    try:
        idents = {}
        for n in only:
            (d / n).mkdir(mode=0o700)
            idents[n] = ensure_link_identity(ss.KEYS[n], IDS[n], d / n)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    inputs = [roster_doc.RosterInput(install_id=IDS[n], label=n, fed_public_key=ss.PUB[IDS[n]], cert=idents[n].cert.der, next_cert=None,
                                     addresses=("127.0.0.1",), link_port=47110, relay_id=None, capabilities=tuple(V2_CAPS)) for n in only]
    return roster_v2.plan_v2(None, inputs, alpha=A, link_peers=links)


def _registry(open_db, lst, trusted=None, closed=False):
    reg = mesh_peers.MeshPeers(open_db=open_db, self_iid=B, fed_dir=Path(tempfile.mkdtemp(prefix="mrf")), sign=ss.KEYS["b"].sign,
                               trusted=trusted or (lambda iid: lst))
    closed_ev = asyncio.Event()
    if closed:
        closed_ev.set()
    session = SimpleNamespace(peer=C, own_sha="s" * 64, mux=SimpleNamespace(closed=closed_ev), extra={})
    reg._entries[C] = mesh_peers._Entry(session=session, transport=None, link=None)  # type: ignore[arg-type]
    reg._lst = lst
    return reg, session


def _row(open_db):
    with closing(open_db()) as conn:
        return peer_hosts.get(conn, C, include_mesh=True)


def test_a_deleted_mesh_row_comes_back_on_the_next_tick_with_the_same_key(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)
    monkeypatch.setattr(mesh, "TICK_SECONDS", 0.05)
    (tmp_path / "b").mkdir()
    b_open = _db(tmp_path / "b")
    holder: dict = {}
    reg_b = mesh_peers.MeshPeers(open_db=b_open, self_iid=B, fed_dir=root / "b", sign=ss.KEYS["b"].sign,
                                 trusted=lambda peer: holder["b"].trusted(peer), ensure=lambda *a, **k: holder["b"].ensure(*a, **k),
                                 touch=lambda iid: holder["b"].touch(iid))

    async def scenario() -> None:
        hooks = {"b": {"on_session": reg_b.session_changed, "on_list": reg_b.list_changed, "on_tick": reg_b.restore_rows,
                       "bind": lambda links: holder.update(b=links)}}
        async with _pair(root, tmp_path, attach=("c",), hooks=hooks) as p:
            monkeypatch.setattr(mesh_peers, "REGISTRY", reg_b)
            await _wait(lambda: C in p.links["b"]._sessions and B in p.links["c"]._sessions)
            await _wait(lambda: reg_b.holds(C) and _row(b_open) is not None)
            first = _row(b_open)
            assert first.back_kind == "mesh"
            with closing(b_open()) as conn:
                hosts_store.delete_host(conn, first.key)
            assert _row(b_open) is None
            await _wait(lambda: _row(b_open) is not None)
            assert _row(b_open).key == first.key and _row(b_open).back_kind == "mesh"

    asyncio.run(scenario())


def test_restore_writes_a_missing_row_for_a_pinned_eligible_member(tmp_path):
    open_db = _db(tmp_path)
    reg, _ = _registry(open_db, _list())
    assert _row(open_db) is None
    asyncio.run(reg.restore_rows())
    assert _row(open_db) is not None and _row(open_db).back_kind == "mesh"


@pytest.mark.parametrize("case", ["link_off", "removed", "unpinned", "closed", "star_row"])
def test_restore_writes_nothing_for_a_computer_that_must_not_have_a_row(tmp_path, case):
    open_db = _db(tmp_path)
    lst = {"link_off": lambda: _list(links={C: False}), "removed": lambda: _list(only=("a", "b"))}.get(case, _list)()
    reg, _ = _registry(open_db, lst, trusted=(lambda iid: None) if case == "unpinned" else None, closed=case == "closed")
    if case == "star_row":
        with closing(open_db()) as conn:
            peer_hosts.upsert(conn, install_id=C, label="c", grant_id="g" * 8, fid="f" * 8, initiator=True)
    asyncio.run(reg.restore_rows())
    with closing(open_db()) as conn:
        rows = [r for r in peer_hosts.list_peers(conn, include_mesh=True) if r.peer_install_id == C]
    assert [r for r in rows if r.back_kind == "mesh"] == [] and (len(rows) == 1) == (case == "star_row")
