
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import src.config  # noqa: F401, E402
from src.core.computers import direction, mesh  # noqa: E402
from src.core.federation import grants, mesh_grants, mesh_powers, peer_sockets  # noqa: E402
from src.core.pack.machines import capabilities, roster_v2  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from tests.python.computers.test_mesh_links import (A, B, C, _identity_in, _inputs, _pair, _v2, _wait, root)  # noqa: E402,F401
from tests.python.federation.test_federation_route_inventory import PEER_ALLOWED, PEER_ALLOWED_SOCKETS  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402


def _edit(lst, iid, **changes):
    return lst.model_copy(update={"computers": [c.model_copy(update=changes) if c.install_id == iid else c for c in lst.computers]})


class _FakeSocket:

    def __init__(self) -> None:
        self.closed = None

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


def _sha(lst, peer=B) -> str:
    entry = lst.entry(peer) if hasattr(lst, "entry") else None
    return entry.shas()[0] if entry is not None else "nosuch"


def _derive(lst, peer=B, self_iid=C, restrictions=None, has_replica=False, cert_sha=None):
    return mesh_grants.derive(lst, self_iid=self_iid, peer_iid=peer, cert_sha=cert_sha or _sha(lst, peer),
                              restrictions=restrictions or Restrictions(), has_replica=has_replica)


def test_derive_table(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    lst, _ = _v2()
    g = _derive(lst)
    assert g is not None and g.peer_install_id == B and g.powers == mesh_powers.ALL_POWERS and not g.one_way
    assert g.grant_id == mesh_grants.grant_id_for(C, B, lst.entry(B).fed_public_key, _sha(lst)) and g.grant_id.startswith("mesh-") and len(g.grant_id) == 45
    assert g.scopes == () and g.issuer == C and g.cert_sha == _sha(lst)
    assert set(g.mesh_scopes) == {"sessions", "machine", "replica"}
    assert g.remote_grant_id is None and g.revoked_at is None and not g.revoked
    assert not {"credentials", "migrate", "refresh", "skills", "global-setup", "settings"} & set(g.mesh_scopes)
    assert "swarm-proxy" not in _derive(lst, has_replica=True).mesh_scopes
    assert "replica" not in _derive(lst, restrictions=Restrictions(may_host_agents=False)).mesh_scopes
    assert _derive(lst, peer="iid-unlisted") is None and _derive(lst, peer=A) is None and _derive(lst, peer=C) is None
    assert _derive(_v2({B: False})[0]) is None and _derive(_v2({C: False})[0]) is None
    assert _derive(_v2(mesh_off=(B,))[0]) is None
    assert _derive(lst.as_v1()) is None and _derive(None) is None
    one = _derive(_edit(lst, B, one_way=True))
    assert one is not None and one.one_way and one.powers == {mesh_powers.MESH_LINK} and set(one.mesh_scopes) == {"sessions"}
    other_key = ss.PUB[A]
    assert _derive(_edit(lst, B, fed_public_key=other_key)).grant_id != g.grant_id
    hinted = _derive(_edit(lst, B, capabilities=[], laptop=True))
    assert hinted is not None and hinted.powers == g.powers and hinted.mesh_scopes == g.mesh_scopes
    assert _derive(lst, cert_sha="f" * 64) is None
    assert mesh_grants.grant_id_for(C, B, lst.entry(B).fed_public_key, "a" * 64) != g.grant_id
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert _derive(lst) is None


def test_a_mesh_grant_satisfies_no_star_scope(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    lst, _ = _v2()
    for grant in (_derive(lst), _derive(_edit(lst, B, one_way=True))):
        assert not any(grant.allows(name) for name in grants.KNOWN_SCOPES)


def test_listed_one_way_reads_only_a_v2_list(monkeypatch):
    lst, _ = _v2()
    assert direction.listed_one_way(_edit(lst, B, one_way=True), B) is True
    assert direction.listed_one_way(lst, B) is False and direction.listed_one_way(lst, "nobody") is False
    assert direction.listed_one_way(lst.as_v1(), B) is False and direction.listed_one_way(None, B) is False


def test_trusted_follows_the_pinned_session_and_dies_with_the_list(monkeypatch, tmp_path, root):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(mesh, "FETCH_DEBOUNCE", 0.0)

    async def scenario() -> None:
        async with _pair(root, tmp_path) as p:
            links, idents, ports, alpha, pack = p.links, p.idents, p.ports, p.alpha, p.pack
            await _wait(lambda: C in links["b"]._sessions and B in links["c"]._sessions)
            lb = links["b"]
            assert lb.trusted(C) is lb._lst and lb.trusted("nobody") is None
            held = lb._lst
            real = lb._custody()

            def swap_list(lst) -> None:
                stub = SimpleNamespace(held_lists=lambda: (lst, None), roster_v2_wire=lambda: None, settings=real.settings)
                lb._custody = lambda: stub

            lb._grace_until = 1e12
            assert lb.trusted(C) is None
            lb._grace_until = None
            lb._lst = held.model_copy(update={"alpha": C})
            assert lb.trusted(C) is None
            lb._lst = held
            assert lb.trusted(C) is held
            swap_list(_edit(held, C, link_peers=False))
            await lb.list_changed()
            assert lb.trusted(C) is None
            assert _derive(lb._lst, peer=C, self_iid=B) is None
            lb._custody = lambda: real
            await lb.list_changed()
            await _wait(lambda: lb.trusted(C) is not None, 12)
            sc_old = lb._sessions[C]
            fresh = _identity_in(root, "c3", ss.KEYS["c"], C)
            assert alpha.refresh_roster(_inputs(idents, ports, certs={"c": fresh.cert.der})).startswith("bump:")
            assert pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            await lb.list_changed()
            assert not lb._pinned(sc_old) and lb.trusted(C) is None
            import threading
            gate, entered = threading.Event(), threading.Event()
            real_certs = mesh.peer_certs

            def slow_certs(*a, **k):
                entered.set()
                gate.wait(5)
                return real_certs(*a, **k)

            monkeypatch.setattr(mesh, "peer_certs", slow_certs)
            task = asyncio.ensure_future(lb.list_changed())
            await _wait(entered.is_set)
            assert lb._lst is not held and lb.trusted(C) is None
            gate.set()
            await task
            monkeypatch.setattr(mesh, "peer_certs", real_certs)
            assert alpha.refresh_roster(_inputs(idents, ports, only=("a", "b"))).startswith("bump:")
            assert pack["b"].custody.merge_roster_v2(alpha.custody.roster_v2_wire(), A)
            await lb.list_changed()
            assert lb.trusted(C) is None and lb._marks == {}

    asyncio.run(scenario())


def test_the_close_hook_kills_a_peer_socket_on_one_way_removal_and_key_change(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    lst, _ = _v2()

    def links_with(held) -> mesh.MeshLinks:
        ml = mesh.MeshLinks.__new__(mesh.MeshLinks)
        ml._lst, ml._iid, ml._grace_until, ml._marks = held, C, None, {}
        return ml

    async def scenario() -> None:
        gid = mesh_grants.grant_id_for(C, B, lst.entry(B).fed_public_key, _sha(lst))
        ml = links_with(lst)
        await ml._close_changed_grants()
        assert ml._marks == {B: (frozenset({gid}), False)}
        rotated = lst.entry(B).model_copy(update={"cert": lst.entry(A).cert})
        for change in ({"one_way": True}, {"fed_public_key": ss.PUB[A]}, {"cert": rotated.cert}, None, "hold"):
            ws = _FakeSocket()
            peer_sockets.register(gid, ws)
            await ml._close_changed_grants()
            assert ws.closed is None and peer_sockets.count(gid) == 1
            if change == "hold":
                ml._grace_until = 1e12
            elif change is None:
                ml._lst = _edit(lst, B, link_peers=False)
            else:
                ml._lst = _edit(lst, B, **change)
            await ml._close_changed_grants()
            assert ws.closed == (peer_sockets.PEER_REVOKED_CODE, peer_sockets.PEER_REVOKED_REASON) and peer_sockets.count(gid) == 0
            ml._lst, ml._grace_until = lst, None
            await ml._close_changed_grants()

    asyncio.run(scenario())


def test_the_power_table_covers_the_star_inventory_and_refuses_what_it_must():
    star = set(PEER_ALLOWED) | {("WS", p) for p in PEER_ALLOWED_SOCKETS}
    assert set(mesh_powers.ROUTES) == star
    for (method, path), power in mesh_powers.ROUTES.items():
        if power == mesh_powers.REFUSED:
            assert (method, path) in mesh_powers.REFUSED_WHY and mesh_powers.power_for(method, path) is None
            continue
        assert power in mesh_powers.ALL_POWERS
        if method != "WS":
            assert PEER_ALLOWED[(method, path)] in mesh_powers.POWER_SCOPES[power], (method, path)
            assert PEER_ALLOWED[(method, path)] not in {"credentials", "skills", "global-setup", "migrate", "refresh"} or power == mesh_powers.MESH_LOGINS, (method, path)
    never = ("/pack/reserve", "/pack/skills/", "/pack/global/blobs", "/pack/global/apply", "/pack/global/panel", "/app-update", "/pack/refresh",
             "/federation/link", "/key/announce", "/grants/self", "/link-cert", "/argent/poll", "/argent/switch", "/pack/gh-login", "/ledger-")
    for (method, path), power in mesh_powers.ROUTES.items():
        if power != mesh_powers.REFUSED:
            assert not any(n in path for n in never), (method, path)
    assert mesh_powers.power_for("GET", "/api/v1/federation/hello") == mesh_powers.MESH_LINK
    assert mesh_powers.power_for("PUT", "/api/v1/federation/pack/restrictions/tighten") == mesh_powers.MESH_TIGHTEN
    assert mesh_powers.power_for("POST", "/api/v1/federation/pack/blobs/abc/seal") == mesh_powers.MESH_JOBS
    assert mesh_powers.power_for("POST", "/api/v1/federation/pack/jobs/start") == mesh_powers.MESH_JOBS
    assert mesh_powers.power_for("GET", "/api/v1/sessions/list") == mesh_powers.MESH_SESSIONS
    assert mesh_powers.power_for("WS", "/ws/terminal") == mesh_powers.MESH_SESSIONS
    assert mesh_powers.power_for("PUT", "/api/v1/federation/pack/reserve") is None
    assert mesh_powers.power_for("GET", "/api/v1/federation/hello/extra") is None and mesh_powers.power_for("GET", "/api/v1/nothing") is None
    assert mesh_powers.power_for("DELETE", "/api/v1/federation/hello") is None
    assert mesh_powers.OPEN_POWERS == {mesh_powers.MESH_LINK, mesh_powers.MESH_LOGINS, mesh_powers.MESH_JOBS, mesh_powers.MESH_DATA}
    assert mesh_powers.power_for("POST", "/api/v1/federation/pack/credentials") == mesh_powers.MESH_LOGINS
    assert mesh_powers.power_for("DELETE", "/api/v1/federation/pack/credentials/codex/work") == mesh_powers.MESH_LOGINS
    assert mesh_powers.power_for("POST", "/api/v1/federation/argent/credential") == mesh_powers.MESH_LOGINS
    assert mesh_powers.power_for("POST", "/api/v1/federation/argent/credential/request") == mesh_powers.MESH_LOGINS
    assert mesh_powers.power_for("POST", "/api/v1/federation/argent/poll") is None and mesh_powers.power_for("POST", "/api/v1/federation/argent/switch") is None
    assert mesh_powers.POWER_SCOPES[mesh_powers.MESH_LOGINS] == {"credentials", "machine"}
