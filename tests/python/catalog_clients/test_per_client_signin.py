
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from types import SimpleNamespace

import httpx
import pytest
import structlog
from fastapi import Request

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pcs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pcs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api.auth import require_auth
from src.core.api_keys.fence import fenced_family
from src.core.catalog import account_push, catalog_auth, client_sessions as cs
from src.core.catalog.token_store import MODE_BOUND, MODE_OWN, CatalogSession, ClientEntry, open_token_store
from src.core.event_hub import EventHub
from src.core.refresh_store import RefreshStore
from src.core.relay_identity import device_key as dk
from tests.helpers.hosted_routes_app import hosted_proxy_app, route_responder

OWNER = "example-owner"


def jwt_of(**claims) -> str:
    enc = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return f"{enc(b'{}')}.{enc(json.dumps(claims).encode())}.sig"


def device_pair(sid="devsid0001"):
    now = int(time.time())
    return CatalogSession(OWNER, jwt_of(sub="acct-1", sid=sid), now + 3600, "DEVICE-REFRESH", now + 99999, "github")


def seed(state, *, minted: bool, clients: dict):
    now = int(time.time())
    with open_token_store(state) as store:
        store.save(device_pair())
        if minted:
            store.flag_set(catalog_auth.FLAG_DEVICE_MINTED, "1")
            store.flag_set(cs.FLAG_DEVICE_ID, "devid123")
        for entry in clients.values():
            store.client_put(entry, now)


def own(key, sid):
    now = int(time.time())
    return ClientEntry(key, MODE_OWN, OWNER, "github", jwt_of(sub="acct-1", sid=sid), now + 3600, f"R-{key}", now + 99999)


def bound(key):
    return ClientEntry(key, MODE_BOUND, OWNER, "github")


def auth(family):
    return {"Authorization": "Bearer " + (jwt_of(sub="u", typ="access", fam=family) if family else jwt_of(sub="u", typ="access"))}


@pytest.fixture
def hosted(tmp_path):
    calls = []

    def record(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization", ""),
                      json.loads(request.content) if request.content else None))
        return (200, {"ok": True})

    responder = route_responder({
        "/auth/signout": record,
        "/auth/sessions/revoke-all": lambda r: (record(r)[0], {"revoked": 2, "kept": 1}),
        "/auth/sessions/device": lambda r: (404, {"code": "not_found"}),
    })
    with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
        def link_aware(request: Request):
            request.scope["via_link"] = request.headers.get("x-test-link") == "1"
            return {"sub": "test"}

        app.client.app.dependency_overrides[require_auth] = link_aware
        app.calls = calls
        yield app


def signed_in(app, family) -> bool:
    body = app.client.get("/catalog/auth/session", headers=auth(family)).json()
    assert "client" in body, body
    return body["client"]["signed_in"]


def test_A_one_client_signs_out_and_the_computer_and_the_others_stay(hosted):
    seed(hosted.state, minted=True, clients={"fam1": own("fam1", "sidfam1aa"), "fam2": own("fam2", "sidfam2bb")})
    with open_token_store(hosted.state) as store:
        before = store.read()
    assert signed_in(hosted, "fam1") and signed_in(hosted, "fam2")

    out = hosted.client.post("/catalog/auth/signout", headers=auth("fam1"))

    assert out.status_code == 200
    assert not signed_in(hosted, "fam1") and signed_in(hosted, "fam2")
    with open_token_store(hosted.state) as store:
        assert store.read() == before
    signouts = [c for c in hosted.calls if c[1].endswith("/auth/signout")]
    assert [json.loads(base64.urlsafe_b64decode(c[2].split()[1].split(".")[1] + "==")).get("sid") for c in signouts] == ["sidfam1aa"]


def test_A_a_pre_upgrade_token_cannot_sign_anything_out(hosted):
    seed(hosted.state, minted=False, clients={"fam1": bound("fam1")})
    answer = hosted.client.post("/catalog/auth/signout", headers=auth(None))
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "refresh_and_retry"
    assert hosted.calls == []
    assert signed_in(hosted, None) and signed_in(hosted, "fam1")


def test_B_signout_all_sends_revoke_all_with_keep_and_include_self(hosted):
    seed(hosted.state, minted=True, clients={"fam1": own("fam1", "sidfam1aa"), "fam2": bound("fam2")})
    refused = hosted.client.post("/catalog/auth/signout-all", headers=auth("fam1"), json={"confirm": False})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "confirm_required"
    assert not [c for c in hosted.calls if c[1].endswith("revoke-all")]

    done = hosted.client.post("/catalog/auth/signout-all", headers=auth("fam1"), json={"confirm": True})

    assert done.status_code == 200 and done.json() == {"kept_device": True}
    sent = [c for c in hosted.calls if c[1].endswith("revoke-all")]
    assert len(sent) == 1
    assert sent[0][3] == {"include_self": True, "keep": [{"sid": "devsid0001", "device_id": "devid123"}]}
    with open_token_store(hosted.state) as store:
        assert store.read() is not None and store.clients_all() == []


def test_B_signout_all_works_over_the_phone_link_with_confirm_and_a_key_is_fenced(hosted):
    seed(hosted.state, minted=True, clients={"phone": bound("phone")})
    headers = {**auth("phone"), "x-test-link": "1"}
    assert hosted.client.post("/catalog/auth/signout-all", headers=headers, json={}).status_code == 403
    assert hosted.client.post("/catalog/auth/signout-all", headers=headers, json={"confirm": True}).status_code == 200
    for path in ("/api/v1/catalog/auth/signout-all", "/api/v1/catalog/computer-account/use",
                 "/api/v1/catalog/account/sessions/revoke-others", "/api/v1/catalog/account/delete"):
        assert fenced_family(path) is not None, path
    from src.core.phone_link.gate import is_denied
    assert is_denied("/api/v1/catalog/computer-account/use") and is_denied("/api/v1/catalog/account/sessions/revoke-others")
    assert not is_denied("/api/v1/catalog/auth/signout-all") and not is_denied("/api/v1/catalog/auth/signout")


def test_D_the_incident_replay_only_the_phones_entry_goes(hosted):
    seed(hosted.state, minted=False, clients={"phone": bound("phone"), "desk": bound("desk")})
    with open_token_store(hosted.state) as store:
        before = store.read()
    with structlog.testing.capture_logs() as logs:
        out = hosted.client.post("/catalog/auth/signout", headers={**auth("phone"), "x-test-link": "1"})
    assert out.status_code == 200
    assert "catalog_signin_cleared" not in [entry["event"] for entry in logs]
    with open_token_store(hosted.state) as store:
        assert store.read() == before
        assert [e.client_key for e in store.clients_all()] == ["desk"]
    over_link = {**auth("desk"), "x-test-link": "1"}
    assert hosted.client.get("/catalog/computer-account/status", headers=over_link).status_code == 403
    assert hosted.client.post("/catalog/computer-account/use", headers=over_link, json={"switch": "x"}).status_code == 403
    assert signed_in(hosted, "desk")


def test_E_a_different_login_is_refused_and_row_one_is_unchanged(tmp_path):
    started = {"device_code": "D", "user_code": "U", "verification_uri": "https://x.test/d", "interval": 5, "expires_in": 900}
    other = {"access_token": jwt_of(sub="acct-2", sid="s2"), "refresh_token": "R2", "expires_in": 3600,
             "refresh_expires_in": 99999, "login": "somebody-else"}
    responder = route_responder({"/auth/device/start": (200, started), "/auth/device/poll": (200, other),
                                 "/auth/signout": (200, {})})
    with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
        app.client.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        seed(app.state, minted=False, clients={"fam1": bound("fam1")})
        with open_token_store(app.state) as store:
            before = store.read()
        flow = app.client.post("/catalog/auth/device/start", headers=auth("fam1")).json()["flow_id"]
        answer = app.client.post("/catalog/auth/device/poll", headers=auth("fam1"), json={"flow_id": flow})
        assert answer.status_code == 409
        detail = answer.json()["detail"]
        assert detail["code"] == "computer_signed_in_as" and detail["login"] == OWNER and detail["switch"]
        assert "R2" not in answer.text and "somebody-else" not in answer.text
        with open_token_store(app.state) as store:
            assert store.read() == before


@pytest.mark.asyncio
async def test_E_remint_is_refused_over_the_link_for_another_login_and_after_a_revoke(tmp_path):
    minted = {"access_token": jwt_of(sub="acct-1", sid="newdev"), "refresh_token": "NR", "expires_in": 3600,
              "refresh_expires_in": 99999, "device_id": "devid123", "session_class": "device"}
    responder = route_responder({"/auth/sessions/device": (200, minted)})
    key = dk.DeviceKey.from_seed(bytes(range(32)))

    async def provider():
        return key

    with hosted_proxy_app(tmp_path, responder=responder) as app:
        now = int(time.time())

        def lose_device():
            with open_token_store(app.state) as store:
                store.clear()
                store.client_put(own("fam1", "sidfam1aa"), now)

        base = "https://catalog.test.invalid/api/v1"
        lose_device()
        link = cs.ClientRef("fam1", via_link=True)
        assert await cs.remint(app.state, base, link, "acct-1", provider) is False
        here = cs.ClientRef("fam1")
        assert await cs.remint(app.state, base, here, "acct-OTHER", provider) is False
        with open_token_store(app.state) as store:
            store.flag_set(catalog_auth.FLAG_DEVICE_REVOKED, "1")
        assert await cs.remint(app.state, base, here, "acct-1", provider) is False
        assert catalog_auth.device_session(app.state) is None and app.sent == []
        with open_token_store(app.state) as store:
            store.flag_clear(catalog_auth.FLAG_DEVICE_REVOKED)
        assert await cs.remint(app.state, base, here, "acct-1", provider) is True
        assert catalog_auth.device_session(app.state).refresh_token == "NR"
        sent = json.loads(app.sent[0].content)
        assert sent["public_key"] == dk.b64url(key.raw_pub) and sent["signature"]


@pytest.mark.asyncio
async def test_F_one_clients_sign_out_push_never_reaches_another_socket(tmp_path):
    hub = EventHub()
    one, two, anon = hub.register(family="fam1"), hub.register(family="fam2"), hub.register()
    account_push.install(SimpleNamespace(event_hub=hub))
    catalog_auth.notify_client("fam1")
    first = json.loads(await one.stream.get())
    assert first == {"type": "account.session", "reread": True} and "signed_in" not in first
    assert two.stream.queued_items == 0 and anon.stream.queued_items == 0
    catalog_auth.notify(None) if hasattr(catalog_auth, "notify") else catalog_auth._notify(None)
    assert one.stream.queued_items == two.stream.queued_items == anon.stream.queued_items == 1


@pytest.mark.asyncio
async def test_a_dead_refresh_family_is_followed_out_of_the_carnivore_sign_in(tmp_path):
    store = RefreshStore(str(tmp_path / "r.db"))
    await store.init()
    heard = []
    store.on_family_dead = heard.append
    await store.issue("jti-a", "u", int(time.time()) + 999)
    await store.issue("jti-b", "u", int(time.time()) + 999)
    assert await store.rotate("jti-a", "jti-a2", "u", int(time.time()) + 999)
    assert await store.family_of("jti-a2") == "jti-a"
    assert sorted(await store.live_families()) == ["jti-a", "jti-b"]
    await store.revoke_chain("jti-a")
    assert heard == [["jti-a"]]
    seed(tmp_path, minted=False, clients={})
    assert cs.migrate(tmp_path, ["jti-b"], ["k1"]) == 2
    assert cs.migrate(tmp_path, ["jti-c"], []) == 0
    with open_token_store(tmp_path) as ts:
        assert sorted(e.client_key for e in ts.clients_all()) == ["apikey:k1", "jti-b"]
    await store.close()


@pytest.fixture
def hosted_revoked(tmp_path):
    responder = route_responder({
        "/auth/signout": lambda r: (200, {"ok": True}),
        "/auth/sessions/revoke-all": lambda r: (401, {"code": "session_revoked"}),
        "/auth/sessions/device": lambda r: (404, {"code": "not_found"}),
    })
    with hosted_proxy_app(tmp_path, responder=responder, include_aggregator=True) as app:
        def allow(request: Request):
            return {"sub": "test"}

        app.client.app.dependency_overrides[require_auth] = allow
        yield app


def test_G_signout_all_answering_401_changes_nothing_and_is_not_success(hosted_revoked):
    seed(hosted_revoked.state, minted=True, clients={"fam1": own("fam1", "sidfam1aa"), "fam2": bound("fam2")})
    done = hosted_revoked.client.post("/catalog/auth/signout-all", headers=auth("fam1"), json={"confirm": True})
    assert done.status_code in (401, 403)
    with open_token_store(hosted_revoked.state) as store:
        assert store.read() is not None
        assert {e.client_key for e in store.clients_all()} == {"fam1", "fam2"}


def test_G_signout_all_needs_a_fam_claim(hosted):
    seed(hosted.state, minted=False, clients={"fam1": bound("fam1")})
    answer = hosted.client.post("/catalog/auth/signout-all", headers=auth(None), json={"confirm": True})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "refresh_and_retry"
    assert hosted.calls == []
    with open_token_store(hosted.state) as store:
        assert store.read() is not None and len(store.clients_all()) == 1


@pytest.mark.asyncio
async def test_G_bound_entries_die_with_the_device_session_and_never_serve_another_login(tmp_path):
    seed(tmp_path, minted=False, clients={"fam1": bound("fam1")})
    assert catalog_auth.forget_if_access_is(tmp_path, device_pair().access_token)
    with open_token_store(tmp_path) as store:
        assert store.clients_all() == []
    seed(tmp_path, minted=False, clients={"fam1": ClientEntry("fam1", MODE_BOUND, "someone-else", "github")})
    with pytest.raises(catalog_auth.SignedOut):
        await catalog_auth.bearer_for(tmp_path, "http://hosted.invalid", "fam1")
