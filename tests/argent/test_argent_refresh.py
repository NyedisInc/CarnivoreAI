
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from src.core.argent import notices, pair_sync, refresh
from src.core.argent.client import ArgentClient, ArgentError
from src.core.argent.delegate import Delegates
from src.core.argent.pair_credential import CAP_CREDENTIAL, CredentialSender
from src.core.argent.refresh import Refresher
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore

OWNER_TOKEN = "OWNER-asicli-fixture-token-000001"
SERVER = "https://cp.argent.test"
T0 = 1_800_000_000.0
H12, D30 = 12 * 3600, 30 * 86400


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class Argent:

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, str]] = []
        self.refresh_status = 200
        self.delegate_route = True
        self.live: Dict[str, str] = {}
        self.n = 0
        self.gate: "asyncio.Event | None" = None

    async def handle(self, request: httpx.Request) -> httpx.Response:
        bearer = request.headers.get("authorization", "")[7:]
        self.calls.append((request.method, request.url.path, bearer))
        if request.url.path == "/v1/my/cli/refresh":
            if self.gate is not None:
                await self.gate.wait()
            if self.refresh_status != 200:
                return httpx.Response(self.refresh_status, json={"error": {"code": "x"}})
            self.n += 1
            return httpx.Response(200, json={"access_token": f"REFRESHED-token-fixture-{self.n:06d}", "expires_in": D30})
        if request.url.path == "/v1/my/cli/delegate":
            if not self.delegate_route:
                return httpx.Response(404)
            self.n += 1
            ident = f"dlg-{self.n}"
            self.live[ident] = f"DELEGATE-token-fixture-{self.n:06d}"
            return httpx.Response(201, json={"id": ident, "access_token": self.live[ident], "expires_in": 86400})
        if request.method == "DELETE" and request.url.path.startswith("/v1/my/cli/delegates/"):
            return httpx.Response(204 if self.live.pop(request.url.path.rsplit("/", 1)[1], None) else 404, json={"error": {"code": "not_found"}})
        return httpx.Response(404)

    def count(self, path: str) -> int:
        return sum(1 for c in self.calls if c[1] == path)


class Rig:
    def __init__(self, tmp: Path, source: str = "own") -> None:
        tmp.mkdir(parents=True, exist_ok=True)
        self.now = [T0]
        self.argent = Argent()
        self.kc = Keychain()
        self.tokens = TokenStore(self.kc)
        self.store = ArgentStore(tmp, clock=lambda: self.now[0])
        self.tokens.write("ten_1", OWNER_TOKEN)
        self.store.set_login("ten_1", "idn_1", "Owner", H12, source=source)
        self.cfg = SimpleNamespace(server_url=SERVER, ca_path="")
        self.transport = httpx.MockTransport(self.argent.handle)
        self.slept: List[float] = []

        async def sleep(seconds: float) -> None:
            self.slept.append(seconds)

        self.refresher = Refresher(self.store, self.tokens, read_settings=lambda: self.cfg, transport=self.transport, clock=lambda: self.now[0],
                                   sleep=sleep, rng=lambda: 0.5)
        self.delegates = Delegates(self.store, self.tokens, read_settings=lambda: self.cfg, transport=self.transport, clock=lambda: self.now[0])


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    monkeypatch.setattr(notices, "pair_login", lambda computer: None)
    return Rig(tmp_path)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_schedule_is_80_percent_of_the_issued_lifetime(rig: Rig) -> None:
    assert rig.refresher.due_at(T0, T0 + H12) == T0 + 0.8 * H12
    rig.now[0] = T0 + 0.79 * H12
    assert run(rig.refresher.check()) == refresh.SKIPPED and rig.argent.count("/v1/my/cli/refresh") == 0
    rig.now[0] = T0 + 0.81 * H12
    assert run(rig.refresher.check()) == refresh.REFRESHED
    assert rig.argent.calls[-1][2] == OWNER_TOKEN
    assert rig.tokens.read("ten_1").startswith("REFRESHED")  # type: ignore[union-attr]
    login = rig.store.get_login()
    assert login["expires_at"] == rig.now[0] + D30 and rig.store.login_issued_at() == rig.now[0] and rig.store.login_source() == "own"
    rig.now[0] += 0.5 * D30
    assert run(rig.refresher.check()) == refresh.SKIPPED


def test_past_due_after_sleep_refreshes_but_expired_needs_a_new_login(rig: Rig) -> None:
    rig.now[0] = T0 + 0.99 * H12
    assert run(rig.refresher.check()) == refresh.REFRESHED
    other = Rig(rig.store._state_dir.parent / "b")  # type: ignore[union-attr]
    other.now[0] = T0 + H12 + 1
    assert run(other.refresher.check()) == refresh.NEEDS_LOGIN
    assert other.argent.count("/v1/my/cli/refresh") == 0 and other.store.login_expired()


def test_single_flight(rig: Rig) -> None:
    async def go() -> List[str]:
        rig.argent.gate = asyncio.Event()
        jobs = [asyncio.ensure_future(rig.refresher.refresh_now()) for _ in range(4)]
        await asyncio.sleep(0.05)
        rig.argent.gate.set()
        return list(await asyncio.gather(*jobs))

    assert run(go()) == [refresh.REFRESHED] * 4 and rig.argent.count("/v1/my/cli/refresh") == 1


def test_401_marks_needs_login_and_never_retries(rig: Rig) -> None:
    rig.argent.refresh_status = 401
    assert run(rig.refresher.refresh_now()) == refresh.NEEDS_LOGIN
    assert rig.argent.count("/v1/my/cli/refresh") == 1 and rig.slept == [] and rig.store.login_expired()
    rig.now[0] = T0 + 0.9 * H12
    assert run(rig.refresher.check()) == refresh.SKIPPED and rig.argent.count("/v1/my/cli/refresh") == 1


def test_5xx_retries_with_backoff_only_while_the_token_is_valid(rig: Rig) -> None:
    rig.argent.refresh_status = 503
    assert run(rig.refresher.refresh_now()) == refresh.UNREACHABLE
    assert rig.argent.count("/v1/my/cli/refresh") == len(refresh.RETRY_DELAYS) + 1 and len(rig.slept) == len(refresh.RETRY_DELAYS)
    assert not rig.store.login_expired()
    rig.now[0] = T0 + H12 + 1
    before = rig.argent.count("/v1/my/cli/refresh")
    assert run(rig.refresher.refresh_now()) == refresh.NEEDS_LOGIN and rig.argent.count("/v1/my/cli/refresh") == before


@pytest.mark.parametrize("source", ["relay:iid-owner", ""])
def test_a_copy_or_unknown_provenance_never_calls_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    monkeypatch.setattr(pair_sync, "copy_unauthorized", lambda: None)
    copy = Rig(tmp_path, source=source)
    copy.now[0] = T0 + 0.95 * H12
    assert run(copy.refresher.check()) == refresh.NOT_OWNER
    assert run(copy.refresher.refresh_now()) == refresh.NOT_OWNER
    assert copy.argent.calls == []


class Mesh:

    def __init__(self, rig: Rig, approved: bool = True, deliver: int = 200) -> None:
        self.wire: List[dict] = []
        self.ok = {"approved": approved, "allows": True, "deliver": deliver}

        async def post(method: str, path: str, body: Any) -> Tuple[int, Any]:
            self.wire.append(body)
            return self.ok["deliver"], {}

        self.sender = CredentialSender(store=rig.store, tokens=rig.tokens, peer=lambda iid: (post, [CAP_CREDENTIAL]), candidates=lambda: ["m1"],
                                       allows=lambda iid: self.ok["allows"], read_settings=lambda: rig.cfg, approved=lambda iid: self.ok["approved"],
                                       clock=lambda: rig.now[0], delegates=rig.delegates, label=lambda iid: "nostromo")


def test_the_relay_sends_a_delegate_and_never_the_owner_token(rig: Rig) -> None:
    mesh = Mesh(rig)
    assert run(mesh.sender.push()) == ["m1"]
    assert mesh.wire[0]["access_token"].startswith("DELEGATE") and OWNER_TOKEN not in str(mesh.wire)
    assert rig.store.delegate_get("m1")["id"] == "dlg-1" and "token" not in str(rig.store.delegate_get("m1")).lower()
    run(mesh.sender.push())
    assert len(mesh.wire) == 1


def test_remint_at_80_percent_kills_the_superseded_delegate_and_a_refresh_sends_nothing(rig: Rig) -> None:
    mesh = Mesh(rig)
    run(mesh.sender.push())
    rig.now[0] = T0 + 0.81 * H12
    run(rig.refresher.check())
    assert len(mesh.wire) == 1 and list(rig.argent.live) == ["dlg-1"]
    rig.now[0] = T0 + 0.81 * 86400
    run(mesh.sender.push())
    assert len(mesh.wire) == 2 and list(rig.argent.live) == ["dlg-3"]
    assert rig.store.delegate_get("m1")["id"] == "dlg-3"


def test_an_undelivered_delegate_is_deleted_and_a_lost_qualification_kills_the_live_one(rig: Rig) -> None:
    mesh = Mesh(rig, deliver=503)
    assert run(mesh.sender.push()) == [] and rig.argent.live == {}
    mesh.ok["deliver"] = 200
    rig.now[0] += 60
    run(mesh.sender.push())
    assert len(rig.argent.live) == 1
    mesh.ok["approved"] = False
    run(mesh.sender.push())
    assert rig.argent.live == {} and rig.store.delegate_get("m1") is None
    mesh.ok.update(approved=True)
    rig.now[0] += 120
    run(mesh.sender.push())
    mesh.ok["allows"] = False
    run(mesh.sender.push())
    assert rig.argent.live == {}


def test_a_member_that_left_the_pack_loses_its_delegate(rig: Rig) -> None:
    mesh = Mesh(rig)
    run(mesh.sender.push())
    mesh.sender._candidates = lambda: []  # type: ignore[attr-defined]
    run(mesh.sender.push())
    assert rig.argent.live == {}


def test_a_missing_delegate_route_sends_nothing_at_all(rig: Rig) -> None:
    rig.argent.delegate_route = False
    mesh = Mesh(rig)
    assert run(mesh.sender.push()) == [] and mesh.wire == []
    assert OWNER_TOKEN not in str(mesh.wire)


def member(tmp: Path, owner_iid: str = "iid-owner") -> Tuple[Rig, pair_sync.PairSync, List[str]]:
    copy = Rig(tmp, source=f"relay:{owner_iid}")
    asked: List[str] = []

    async def post(method: str, path: str, body: Any) -> Tuple[int, Any]:
        asked.append(path)
        return 200, {}

    sync = pair_sync.PairSync(store=copy.store, tokens=copy.tokens, self_id="iid-me", self_label="me", peer=lambda iid: (post, [CAP_CREDENTIAL]),
                              listing=lambda: [(owner_iid, "owner", "up", [CAP_CREDENTIAL])], candidates=lambda: [], allows=lambda iid: True,
                              state_dir=tmp)
    return copy, sync, asked


def test_a_member_401_asks_the_owner_once_and_never_flags_the_login(tmp_path: Path) -> None:
    copy, sync, asked = member(tmp_path)

    async def go() -> List[str]:
        return [await sync.ask_owner(), await sync.ask_owner()]

    assert run(go()) == ["asked", "already_asked"] and asked == [pair_sync.REQUEST_PATH]
    copy.store.mark_login_expired()
    assert not copy.store.login_expired()


def test_an_unreachable_owner_reads_as_waiting_and_a_delegate_403_changes_nothing(tmp_path: Path) -> None:
    copy, sync, _ = member(tmp_path)
    sync._peer = sync._cred_peer = lambda iid: None  # type: ignore[assignment]
    assert run(sync.ask_owner()) == "waiting_on_owner" and sync.view()["waiting_on_owner"] == "iid-owner"

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "delegate_not_allowed"}})

    client = ArgentClient(SERVER, lambda: "x", transport=httpx.MockTransport(forbidden), on_unauthorized=copy.store.mark_login_expired)
    with pytest.raises(ArgentError) as raised:
        run(client.post("/v1/my/cli/refresh"))
    assert raised.value.code == "delegate_not_allowed" and not copy.store.login_expired()




def test_concurrent_pushes_mint_once_and_the_id_is_recorded_before_the_send(rig: Rig) -> None:
    mesh = Mesh(rig)
    seen: List[Any] = []
    original = mesh.sender._post

    async def spying(post: Any, iid: str, body: dict) -> str:
        seen.append(rig.store.delegate_get(iid))
        await asyncio.sleep(0.01)
        return await original(post, iid, body)

    mesh.sender._post = spying  # type: ignore[method-assign]

    async def go() -> None:
        await asyncio.gather(mesh.sender.push(), mesh.sender.push(), mesh.sender.push())

    run(go())
    assert rig.argent.count("/v1/my/cli/delegate") == 1 and len(seen) == 1
    assert [e["id"] for e in seen[0]["stale"]] == ["dlg-1"]


def test_forced_requests_are_rate_limited_and_ignored_while_in_flight(rig: Rig) -> None:
    mesh = Mesh(rig)
    run(mesh.sender.push())
    for _ in range(5):
        run(mesh.sender.push("m1", force=True))
    assert rig.argent.count("/v1/my/cli/delegate") == 2 and len(rig.argent.live) == 1
    rig.now[0] += 61
    run(mesh.sender.push("m1", force=True))
    assert rig.argent.count("/v1/my/cli/delegate") == 3 and len(rig.argent.live) == 1


def test_a_delete_that_is_a_404_is_pending_not_revoked_and_a_new_login_kills_the_old_chain_first(rig: Rig) -> None:
    mesh = Mesh(rig)
    run(mesh.sender.push())
    rig.argent.live.clear()
    run(rig.delegates.revoke_all())
    rec = rig.store.delegate_get("m1")
    assert rec is not None and [e["id"] for e in rec["stale"]] == ["dlg-1"] and rec["id"] == ""
    assert [c for c in rig.argent.calls if c[0] == "DELETE"][-1][2] == OWNER_TOKEN
    rig.now[0] += 2 * 86400
    run(rig.delegates.revoke_all())
    assert rig.store.delegate_get("m1") is None


def test_delivery_failure_with_a_failed_delete_stays_tracked_and_backs_off(rig: Rig) -> None:
    mesh = Mesh(rig, deliver=503)
    rig.argent.live_delete_fails = True  # type: ignore[attr-defined]
    original = rig.argent.handle

    async def failing(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(500)
        return await original(request)

    rig.delegates._transport = httpx.MockTransport(failing)
    assert run(mesh.sender.push()) == []
    assert [e["id"] for e in rig.store.delegate_get("m1")["stale"]] == ["dlg-1"]
    run(mesh.sender.push())
    assert rig.argent.count("/v1/my/cli/delegate") == 1
    rig.now[0] += 31
    run(mesh.sender.push())
    assert rig.argent.count("/v1/my/cli/delegate") == 2
    rig.now[0] += 31
    run(mesh.sender.push())
    assert rig.argent.count("/v1/my/cli/delegate") == 2


def test_provenance_is_checked_again_on_every_attempt(rig: Rig) -> None:
    rig.argent.refresh_status = 503

    async def flip(seconds: float) -> None:
        rig.store.set_login("ten_1", "idn_1", "Owner", H12, source="relay:iid-x")

    rig.refresher._sleep = flip  # type: ignore[assignment]
    run(rig.refresher.refresh_now())
    assert rig.argent.count("/v1/my/cli/refresh") == 1


def test_a_failed_keychain_write_keeps_the_new_token_and_stop_never_cancels_a_rotation(rig: Rig) -> None:
    from src.core.argent.token_store import TokenUnavailable

    real, fail = rig.tokens.write, [True]

    def flaky(tenant: str, token: str) -> None:
        if fail[0]:
            raise TokenUnavailable("x")
        real(tenant, token)

    rig.tokens.write = flaky  # type: ignore[method-assign]
    rig.refresher._read_settings = lambda: rig.cfg
    assert run(rig.refresher.refresh_now()) == refresh.UNREACHABLE and rig.refresher._unsaved is not None
    fail[0] = False
    assert run(rig.refresher.refresh_now()) == refresh.REFRESHED
    assert rig.argent.count("/v1/my/cli/refresh") == 1 and rig.tokens.read("ten_1").startswith("REFRESHED")  # type: ignore[union-attr]

    async def stopping() -> str:
        rig.argent.gate = asyncio.Event()
        job = asyncio.ensure_future(rig.refresher.refresh_now())
        await asyncio.sleep(0.05)
        halt = asyncio.ensure_future(rig.refresher.stop())
        await asyncio.sleep(0.05)
        assert not halt.done()
        rig.argent.gate.set()
        await halt
        return await job

    assert run(stopping()) == refresh.REFRESHED and rig.refresher._handle is None


def test_the_request_route_uses_the_machine_scope_and_works_for_a_listed_member(rig: Rig) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.argent import pair
    from src.api.peer_auth import Principal

    assert pair._require_machine.peer_scope == "machine"  # type: ignore[attr-defined]
    mesh = Mesh(rig)
    app = FastAPI()
    app.include_router(pair.federation_router, prefix="/api/v1")
    app.dependency_overrides[pair._require_machine] = lambda: Principal("peer", SimpleNamespace(peer_install_id="m1"))
    real = pair._sync
    pair._sync = lambda: SimpleNamespace(credentials_requested=lambda sender: mesh.sender.push(sender, force=True))  # type: ignore[assignment]
    try:
        reply = TestClient(app).post("/api/v1/federation/argent/credential/request", json={})
    finally:
        pair._sync = real  # type: ignore[assignment]
    assert reply.status_code == 200 and len(mesh.wire) == 1 and mesh.wire[0]["access_token"].startswith("DELEGATE")


def test_an_unlisted_sender_request_is_ignored(tmp_path: Path) -> None:
    copy, sync, _ = member(tmp_path)
    run(sync.credentials_requested("iid-stranger"))


def test_an_unsaved_token_is_never_written_after_a_logout(rig: Rig) -> None:
    from src.core.argent.token_store import TokenUnavailable

    real = rig.tokens.write

    def broken(tenant: str, token: str) -> None:
        raise TokenUnavailable("x")

    rig.tokens.write = broken  # type: ignore[method-assign]
    assert run(rig.refresher.refresh_now()) == refresh.UNREACHABLE and rig.refresher._unsaved is not None
    rig.tokens.write = real  # type: ignore[method-assign]
    rig.store.clear_login()
    rig.tokens.delete("ten_1")
    assert run(rig.refresher._save()) is False
    assert rig.store.get_login() is None and rig.tokens.read("ten_1") is None and rig.refresher._unsaved is None
