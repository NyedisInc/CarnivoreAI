
import json

import httpx
import pytest

from tests.phone_link.pairing_helpers import pair_device
from fastapi import FastAPI

from src.api import account_gates
from src.api import phone_link_routes as routes
from src.api.auth import require_auth
from src.config.relay import RelayConfig
from src.core import resource_push
from src.core.catalog import hosted_api
from src.core.phone_link import acme
from src.core.phone_link.custom_domain import dns_gate
from src.core.phone_link.custom_domain import service as svc_mod
from src.core.phone_link.manager import PhoneLinkManager
from src.core.relay_identity import device_key as dk
from src.core.resource_push import topics
from src.core.relay_identity.session import SIGNIN_REQUIRED, RelayAuthError

DOMAIN = "sync.example.com"
ACCT = "https://acme-v02.api.letsencrypt.org/acme/acct/12345"


def view(state="pending", **over):
    base = {"domain": DOMAIN, "state": state, "target": "dev.d.link.carnivore.ai", "dead_reason": None,
            "lockout_until": None, "check": {"result": "no_cname", "seen": None, "checked_at": 1}, "repair": 0}
    return {**base, **over}


class FakeSession:

    def __init__(self, bearer="bearer"):
        self.k, self.bearer, self.dropped = dk.DeviceKey.from_seed(bytes(range(32))), bearer, 0

    async def key(self):
        return self.k

    async def account_bearer(self):
        return self.bearer

    async def ensure_registered(self):
        return self.k.device_id

    def drop_token(self):
        self.dropped += 1


class Control:

    def __init__(self):
        self.calls, self.reply = [], (200, view())

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        self.calls.append((path, json_body, bearer))
        status, body = self.reply
        return hosted_api.HostedAnswer(status, body)


class Manager(PhoneLinkManager):
    async def _start(self):
        pass

    async def _stop(self):
        pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pushed = []
    monkeypatch.setattr(resource_push, "notify", pushed.append)
    mgr = Manager(app=None, config=RelayConfig(), state_dir=tmp_path, db_path=tmp_path / "c.db", version="1.0.0")
    session, control = FakeSession(), Control()
    mgr._session = session
    mgr.custom._call = control
    mgr.custom._acct_uri = ACCT

    async def no_sleep(_seconds):
        return None

    mgr.custom._sleep = no_sleep
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.state.phone_link = mgr
    app.dependency_overrides[require_auth] = lambda: True
    app.dependency_overrides[account_gates.require_account("phone_link")] = lambda: None
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://x.test")
    yield mgr, client, control, session, pushed
    mgr.pairing.close()


@pytest.mark.asyncio
async def test_get_with_no_binding_is_state_none(rig):
    _, client, *_ = rig
    body = (await client.get("/api/v1/phone-link/custom-domain")).json()
    assert body == {"domain": None, "domain_display": None, "state": "none", "target": None, "dead_reason": None,
                    "lockout_until": None, "check": None, "cert": None, "error": None, "updated_at": 0}


@pytest.mark.asyncio
async def test_put_signs_a_submit_with_the_account_uri_and_the_bearer_and_pushes(rig):
    mgr, client, control, session, pushed = rig
    r = await client.put("/api/v1/phone-link/custom-domain", json={"domain": " Sync.Example.com "})
    assert r.status_code == 200
    body = r.json()
    assert body["domain"] == DOMAIN and body["state"] == "pending" and body["target"] == "dev.d.link.carnivore.ai"
    assert body["check"]["result"] == "no_cname"
    ((path, sent, bearer),) = control.calls
    assert path == "/custom-domain" and bearer == "bearer"
    assert (sent["action"], sent["domain"], sent["acct_uri"], sent["device_id"]) == ("submit", DOMAIN, ACCT, session.k.device_id)
    message = dk.custom_domain_message(sent["device_id"], sent["ts"], dk.unb64url(sent["nonce"]), "submit", DOMAIN, ACCT)
    from src.core.relay_identity.device_key import unb64url
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(session.k.raw_pub).verify(unb64url(sent["sig"]), message)
    assert topics.CUSTOM_DOMAIN in pushed
    assert (await client.get("/api/v1/phone-link/custom-domain")).json()["state"] == "pending" and len(control.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,reason", [("example.com", "apex"), ("*.a.example.com", "wildcard"), ("co.uk", "public_suffix")])
async def test_put_refuses_a_bad_name_before_signing_anything(rig, raw, reason):
    _, client, control, *_ = rig
    r = await client.put("/api/v1/phone-link/custom-domain", json={"domain": raw})
    assert r.status_code == 400 and r.json()["code"] == "bad_domain" and r.json()["reason"] == reason
    assert control.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,expected", [
    (409, "domain_exists", 409), (429, "cd_limit", 429), (403, "account_required", 403),
    (400, "bad_domain", 400), (503, "unavailable", 502)])
async def test_put_relays_the_control_planes_refusal(rig, status, code, expected):
    _, client, control, *_ = rig
    control.reply = (status, {"code": code, "detail": "apex"})
    r = await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    assert r.status_code == expected
    assert r.json()["code"] == ("control_unreachable" if expected == 502 else code)
    if code == "bad_domain":
        assert r.json()["reason"] == "apex"


@pytest.mark.asyncio
async def test_put_signed_out_is_account_required_and_signs_nothing(rig):
    mgr, client, control, session, _ = rig
    session.bearer = None
    r = await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    assert r.status_code == 403 and r.json()["code"] == "account_required" and control.calls == []


@pytest.mark.asyncio
async def test_delete_removes_the_binding_and_the_certificate_files(rig):
    mgr, client, control, _, pushed = rig
    await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    certs_dir = mgr.custom._certs.cert_path.parent
    certs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("cert.pem", "cert.key", "cert.json"):
        (certs_dir / name).write_text("x")
    control.reply = (200, view("dead", dead_reason="removed"))
    pushed.clear()
    r = await client.delete("/api/v1/phone-link/custom-domain")
    assert r.status_code == 200 and r.json()["state"] == "none" and r.json()["domain"] is None
    assert control.calls[-1][1]["action"] == "remove" and control.calls[-1][1]["domain"] == DOMAIN
    assert not any((certs_dir / n).exists() for n in ("cert.pem", "cert.key", "cert.json"))
    assert topics.CUSTOM_DOMAIN in pushed


@pytest.mark.asyncio
async def test_remove_on_a_name_the_control_plane_holds_dead_clears_it_and_a_failure_keeps_it(rig):
    mgr, client, control, _, _ = rig
    await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    control.reply = (200, view("dead", dead_reason="removed"))
    mgr.custom._commit(view=mgr.custom._view | {"state": "dead", "dead_reason": "removed"}, error="control_unreachable")
    control.reply = (503, {"code": "down"})
    r = await client.delete("/api/v1/phone-link/custom-domain")
    assert r.status_code == 502 and r.json()["code"] == "control_unreachable" and mgr.custom.state == "dead"
    control.reply = (200, view("dead", dead_reason="removed"))
    r = await client.delete("/api/v1/phone-link/custom-domain")
    assert r.status_code == 200 and r.json()["state"] == "none" and r.json()["error"] is None
    assert (await client.get("/api/v1/phone-link/custom-domain")).json()["domain"] is None


@pytest.mark.asyncio
async def test_a_status_poll_commits_the_new_state_and_a_failure_is_the_named_error(rig):
    mgr, client, control, _, pushed = rig
    await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    control.reply = (200, view("live"))
    pushed.clear()
    await mgr.custom.refresh()
    assert mgr.custom.state == "live" and mgr.custom.name() == DOMAIN and topics.CUSTOM_DOMAIN in pushed
    control.reply = (503, {"code": "unavailable"})
    pushed.clear()
    await mgr.custom.refresh()
    snap = (await client.get("/api/v1/phone-link/custom-domain")).json()
    assert snap["error"] == "control_unreachable" and snap["state"] == "live" and topics.CUSTOM_DOMAIN in pushed
    control.reply = (200, view("live"))
    await mgr.custom.refresh()
    assert (await client.get("/api/v1/phone-link/custom-domain")).json()["error"] is None


@pytest.mark.asyncio
async def test_a_view_with_a_larger_repair_epoch_revokes_pairings_before_it_is_adopted(rig):
    mgr, client, control, _, pushed = rig
    pair_device(mgr.pairing, "203.0.113.5", host=DOMAIN)

    async def no_push_store(device_id):
        mgr.pairing.revoke(device_id)

    mgr._repair._revoke = no_push_store
    control.reply = (200, view("pending", repair=3))
    await client.put("/api/v1/phone-link/custom-domain", json={"domain": DOMAIN})
    assert mgr.pairing.device_count() == 0 and mgr._repair.seen() == 3


@pytest.mark.asyncio
async def test_the_pairing_window_url_uses_the_custom_name_only_when_live_with_a_certificate(rig):
    mgr, client, control, *_ = rig
    mgr.hostname = "dev.link.carnivore.ai"
    await mgr.set_enabled(True)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.state.phone_link = mgr
    app.dependency_overrides[require_auth] = lambda: True
    app.dependency_overrides[account_gates.require_account("phone_pairing")] = lambda: None
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://x.test")
    assert (await c.post("/api/v1/phone-link/pairing-window")).json()["url"].startswith("https://dev.link.carnivore.ai/pair#")
    mgr.custom._commit(view("live"))
    mgr.custom._ready = True
    live = (await c.post("/api/v1/phone-link/pairing-window")).json()["url"]
    assert live.startswith(f"https://{DOMAIN}/pair?link=dev#")
    assert live.count("#") == 1 and "?" not in live.split("#")[1]
    assert "?" not in (await c.post("/api/v1/phone-link/pairing-window")).json()["pair_url"]
    mgr.custom._ready = False
    assert (await c.post("/api/v1/phone-link/pairing-window")).json()["url"].startswith("https://dev.link.carnivore.ai/pair#")




class FakeTunnel:
    def __init__(self, connected=True):
        self.connected, self.events = connected, []

    async def reauth_now(self):
        self.events.append("reauth")
        return self.connected


@pytest.mark.asyncio
async def test_the_order_waits_for_a_connected_tunnel_and_a_reauth_after_live(rig, monkeypatch):
    mgr, _, control, session, _ = rig

    async def pinned(node, acct):
        return True

    monkeypatch.setattr(dns_gate, "pin_visible", pinned)
    service = mgr.custom
    service._commit(view("live"))
    tunnel = FakeTunnel(connected=False)
    service._tunnel = tunnel
    order = []

    async def renew(domain):
        order.append(("renew", domain, list(tunnel.events)))

    service._certs.renew = renew

    async def noop():
        pass

    service._refresh_cert_flag = noop
    await service._claim_then_order(DOMAIN)
    assert order == [] and tunnel.events == []
    tunnel.connected = True
    await service._claim_then_order(DOMAIN)
    assert order == [("renew", DOMAIN, ["reauth"])]
    assert session.dropped == 1
    await service._claim_then_order(DOMAIN)
    assert tunnel.events == ["reauth"] and len(order) == 2


@pytest.mark.asyncio
async def test_a_failed_order_is_the_named_error_and_retries_in_an_hour(rig):
    mgr, _, _, _, pushed = rig
    service = mgr.custom
    service._commit(view("live"))

    async def renew(domain):
        raise acme.AcmeError("urn:ietf:params:acme:error:rejectedIdentifier")

    service._certs.renew = renew
    await service._order(DOMAIN)
    assert service.snapshot()["error"] == "certificate_failed"
    assert service._next_order >= service._clock() + svc_mod.ORDER_RETRY - 5 and not service._order_open


@pytest.mark.asyncio
async def test_the_tunnel_stays_wanted_while_a_live_name_has_no_certificate(rig):
    mgr = rig[0]
    await mgr.set_enabled(True)
    assert mgr.wanted() is False
    mgr.custom._commit(view("live"))
    assert mgr.wanted() is True
    mgr.custom._ready = True
    import datetime as dt
    mgr.custom._not_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=100)
    assert mgr.wanted() is False
    mgr.custom._not_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=10)
    assert mgr.wanted() is True


@pytest.mark.asyncio
async def test_the_sync_switch_is_told_to_the_control_plane_and_retried(rig):
    mgr, _, control, *_ = rig
    mgr.custom._commit(view("live"))
    await mgr.set_enabled(False)
    mgr.custom._next_status = 1e12
    control.reply = (503, {"code": "unavailable"})
    await mgr.custom._tick()
    assert control.calls and control.calls[-1][1]["action"] == "sync_off"
    assert mgr.pairing.setting(svc_mod.SYNC_SETTING) == "off"
    mgr.custom._next_sync = 0.0
    control.reply = (200, view("live"))
    await mgr.custom._tick()
    assert mgr.pairing.setting(svc_mod.SYNC_SETTING) == ""
    assert [c[1]["action"] for c in control.calls if c[1]["action"].startswith("sync")][-1] == "sync_off"


def test_status_polling_follows_the_pending_ladder_then_every_six_hours(rig):
    service = rig[0].custom
    service._commit(view("pending"))
    seen = []
    for polls in range(6):
        service._pending_polls = polls
        service._next_status = 0.0
        service._schedule_status()
        seen.append(round(service._next_status - service._clock()))
    assert seen == [30, 60, 120, 300, 600, 600]
    service._commit(view("live"))
    service._schedule_status()
    assert round(service._next_status - service._clock()) == 6 * 3600


def test_refresh_soon_makes_the_next_tick_read_status(tmp_path):
    from src.core.phone_link.custom_domain.service import CustomDomainService
    from src.core.phone_link.pairing import PairingStore
    store = PairingStore(path=tmp_path / "p.db")
    svc = CustomDomainService(pairing=store, state_dir=tmp_path, directory_url="x", control_url="x",
                              get_session=None, reconcile=None, repair=None, sync_on=lambda: False)
    svc._commit(view("live"))
    svc._next_status = 1e12
    svc.refresh_soon()
    assert svc._next_status == 0.0 and svc._wake.is_set()
    store.close()
