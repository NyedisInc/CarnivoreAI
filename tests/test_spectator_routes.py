
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_specrt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_specrt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
)

from src.core.relay_e2ee import derive_link_keys
from src.core.spectator_links_store import (
    MAX_TTL_SECONDS,
    MIN_TTL_SECONDS,
    SpectatorLinksStore,
)
from src.core.relay_publisher import RelayPublisher

SESSION_ID = "ses_share_probe"
OTHER_SESSION_ID = "ses_other_probe"

RELAY_PUBLISH_URL = "wss://relay.example.test/publish"


def _publisher(connected: bool) -> RelayPublisher:
    publisher = RelayPublisher(
        url=RELAY_PUBLISH_URL, credentials=None, registry=None, declarations=None
    )
    publisher._connected = connected
    return publisher


def _relay_over(store: SpectatorLinksStore, publisher):
    from src.core.relay_lifecycle import RelayLifecycle

    if publisher is None:
        return None

    async def has_live_links() -> bool:
        return bool(await store.live_expiry_by_session())

    lifecycle = RelayLifecycle(start=lambda: publisher, has_live_links=has_live_links)
    lifecycle._publisher = publisher
    return lifecycle


async def _awaited(task) -> None:
    await task


def _use(client, publisher) -> None:
    client.app.state.relay = _relay_over(client.app.state.spectator_links, publisher)


def _build_app(store: SpectatorLinksStore):
    from fastapi import FastAPI

    from src.api import spectator_routes
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session

    @asynccontextmanager
    async def lifespan(app):
        await store.init()
        app.state.spectator_links = store
        app.state.relay = _relay_over(store, _publisher(True))
        yield
        await store.close()

    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), None)
    registry.register(Session(id=OTHER_SESSION_ID, working_dir="/tmp"), None)

    app = FastAPI(lifespan=lifespan)
    app.state.services = SimpleNamespace(registry=registry)
    app.include_router(spectator_routes.router, prefix="/api/v1")
    from src.api import account_gates

    app.dependency_overrides[account_gates.require_account("share_link")] = lambda: None
    return app


@pytest.fixture
def store(tmp_path):
    return SpectatorLinksStore(str(tmp_path / "cloude.db"))


@pytest.fixture
def client(store):
    from fastapi.testclient import TestClient

    with TestClient(_build_app(store)) as entered:
        yield entered


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {_mint_token()}"}


def _mint(client, auth, session_id=SESSION_ID, **body):
    return client.post(
        f"/api/v1/sessions/{session_id}/spectator-links", json=body, headers=auth
    )


def test_the_owners_list_serves_a_live_links_url_and_nothing_else(client, auth):
    minted = _mint(client, auth, ttl_seconds=600, label="demo")
    assert minted.status_code == 200, minted.text
    body = minted.json()
    assert "#" in body["url"], (
        f"the mint did not return a fragment-carried link: {body['url']!r}"
    )
    token = body["url"].split("#", 1)[1]
    assert len(token) >= 32, "the token is too short to be 32 random bytes"

    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    )
    assert listed.status_code == 200
    rows = listed.json()["links"]
    assert [row["id"] for row in rows] == [body["id"]]
    assert rows[0]["url"] == body["url"]
    assert rows[0]["label"] == "demo"


def test_a_revoked_or_expired_links_url_is_never_served(client, auth, monkeypatch):
    import src.core.spectator_links_store as store_mod

    revoked = _mint(client, auth, ttl_seconds=600).json()
    client.delete(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links/{revoked['id']}",
        headers=auth,
    )
    expiring = _mint(client, auth, OTHER_SESSION_ID, ttl_seconds=600).json()
    store = client.app.state.spectator_links

    def assert_never_served(minted, session_id):
        token = minted["url"].split("#", 1)[1]
        listed = client.get(
            f"/api/v1/sessions/{session_id}/spectator-links", headers=auth
        )
        assert listed.status_code == 200
        assert token not in listed.text, (
            f"a dead link's token was served by the owner's list: {minted['id']}"
        )
        assert client.portal.call(store.live_token, minted["id"]) is None

    assert_never_served(revoked, SESSION_ID)
    assert client.portal.call(store.live_token, expiring["id"]) is not None

    real = store_mod.time.time
    monkeypatch.setattr(store_mod, "time", SimpleNamespace(time=lambda: real() + 601))
    assert_never_served(expiring, OTHER_SESSION_ID)


def test_the_list_names_no_url_without_a_relay_publisher(client, auth):
    _mint(client, auth, ttl_seconds=600)
    _use(client, None)
    rows = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    ).json()["links"]
    assert len(rows) == 1 and rows[0]["url"] is None


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"/api/v1/sessions/{SESSION_ID}/spectator-links"),
        ("get", f"/api/v1/sessions/{SESSION_ID}/spectator-links"),
        ("delete", f"/api/v1/sessions/{SESSION_ID}/spectator-links/whatever"),
    ],
)
def test_every_route_needs_the_owners_own_token(client, auth, method, path):
    refused = getattr(client, method)(path)
    assert refused.status_code == 401, (
        f"{method.upper()} {path} answered {refused.status_code} with no "
        "bearer token"
    )
    allowed = getattr(client, method)(path, headers=auth)
    assert allowed.status_code != 401, (
        "the authenticated call was refused too, so the 401 above says "
        "nothing about authentication"
    )


@pytest.mark.parametrize(
    "ttl,expected",
    [
        (None, 200),
        (MIN_TTL_SECONDS, 200),
        (MAX_TTL_SECONDS, 200),
        (MIN_TTL_SECONDS - 1, 422),
        (MAX_TTL_SECONDS + 1, 422),
        (0, 422),
        (-3600, 422),
    ],
)
def test_a_ttl_outside_the_bounds_is_refused_rather_than_clamped(
    client, auth, ttl, expected
):
    body = {} if ttl is None else {"ttl_seconds": ttl}
    response = _mint(client, auth, **body)
    assert response.status_code == expected, response.text


def test_a_share_cannot_be_minted_for_a_session_this_server_does_not_have(
    client, auth
):
    assert _mint(client, auth, session_id="ses_typo").status_code == 404
    assert _mint(client, auth).status_code == 200


def test_revoking_ends_the_share_and_drops_it_from_the_relay_set(client, auth):
    minted = _mint(client, auth, ttl_seconds=600).json()
    kept = _mint(client, auth, session_id=OTHER_SESSION_ID, ttl_seconds=600).json()
    revoked = client.delete(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links/{minted['id']}",
        headers=auth,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"id": minted["id"]}

    store = client.app.state.spectator_links
    declared = [lid for lid, *_ in client.portal.call(store.live_relay_declarations)]
    assert declared == [kept["id"]], (
        f"the relay would still be told about a revoked link: {declared!r}"
    )

    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    ).json()
    assert listed["links"] == [], (
        "a revoked link is still offered in the owner's list, where the "
        "only thing to do with it is revoke it again"
    )


def test_a_link_cannot_be_revoked_through_another_sessions_url(client, auth):
    minted = _mint(client, auth, session_id=SESSION_ID).json()

    wrong = client.delete(
        f"/api/v1/sessions/{OTHER_SESSION_ID}/spectator-links/{minted['id']}",
        headers=auth,
    )
    assert wrong.status_code == 404, (
        f"a link was revoked through the wrong session's url: {wrong.text}"
    )
    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    ).json()["links"]
    assert [row["id"] for row in listed] == [minted["id"]], (
        "the refused revoke still ended the link"
    )

    right = client.delete(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links/{minted['id']}",
        headers=auth,
    )
    assert right.status_code == 200, right.text


def test_an_unknown_link_is_a_404_and_not_a_silent_success(client, auth):
    missing = client.delete(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links/no-such-link",
        headers=auth,
    )
    assert missing.status_code == 404


def test_there_is_no_local_spectate_page():
    from fastapi.testclient import TestClient

    import src.main as main_mod

    client = TestClient(main_mod.app)
    assert client.get("/spectate").status_code == 404
    assert client.get("/spectate/").status_code == 404
    page = client.get("/session")
    assert page.status_code == 200 and "text/html" in page.headers.get("content-type", "")


def test_minting_again_replaces_the_live_link_and_takes_it_off_the_relay(client, auth):
    first = _mint(client, auth, ttl_seconds=600).json()
    second = _mint(client, auth, ttl_seconds=600).json()
    assert second["id"] != first["id"]

    store = client.app.state.spectator_links
    declared = [lid for lid, *_ in client.portal.call(store.live_relay_declarations)]
    assert declared == [second["id"]], (
        f"the displaced link is still declared to the relay: {declared!r}"
    )
    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    ).json()["links"]
    assert [row["id"] for row in listed] == [second["id"]], (
        f"the session is offering more than one live share: {listed!r}"
    )


def test_mint_revoke_and_replace_each_poke_the_publisher(client, auth):
    pokes = []
    client.app.state.relay.publisher.poke = lambda: pokes.append("poke")

    first = _mint(client, auth, ttl_seconds=600).json()
    assert len(pokes) == 1, "the mint did not poke the publisher"

    second = _mint(client, auth, ttl_seconds=600).json()
    assert len(pokes) == 2, (
        "the second mint (which replaces and revokes the first link) "
        "did not poke the publisher"
    )

    revoked = client.delete(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links/{second['id']}",
        headers=auth,
    )
    assert revoked.status_code == 200, revoked.text
    assert len(pokes) == 3, "the revoke route did not poke the publisher"
    lifecycle = client.app.state.relay
    assert lifecycle._stop_task is not None, "the revoke scheduled no stop"
    client.portal.call(_awaited, lifecycle._stop_task)
    assert lifecycle.publisher is None, "the last revoke left the relay connected"


def test_the_mint_hands_out_the_relay_viewer_url(client, auth):
    on = _mint(client, auth, ttl_seconds=600).json()
    sent, _, token = on["url"].partition("#")
    assert sent == f"https://relay.example.test/s/{on['id']}", on["url"]
    assert len(token) >= 32 and token not in sent
    assert "testserver" not in on["url"] and "/spectate" not in on["url"]


@pytest.mark.parametrize(
    "publisher,reason",
    [
        (None, "the relay publisher is not running"),
        (False, "the relay publisher is not connected"),
    ],
    ids=["publisher-absent", "publisher-disconnected"],
)
def test_the_mint_is_refused_when_the_relay_is_unavailable(
    client, auth, publisher, reason
):
    _use(client, None if publisher is None else _publisher(publisher))
    refused = _mint(client, auth, ttl_seconds=600)
    assert refused.status_code == 503, refused.text
    assert refused.json()["detail"] == {"code": "relay_unavailable", "reason": reason}
    assert "url" not in refused.text
    if publisher is not None:
        client.portal.call(_awaited, client.app.state.relay._stop_task)

    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth
    ).json()
    assert listed == {"links": [], "relay_available": publisher is not None}, (
        f"a refused mint still wrote a share: {listed!r}"
    )
    assert publisher is None or client.app.state.relay.publisher is None, (
        "a refused mint left a publisher running with nothing shared"
    )

    _use(client, _publisher(True))
    assert _mint(client, auth, ttl_seconds=600).status_code == 200


def test_the_list_says_whether_the_relay_can_take_a_link(client, auth):
    url = f"/api/v1/sessions/{SESSION_ID}/spectator-links"
    assert client.get(url, headers=auth).json()["relay_available"] is True
    _use(client, _publisher(False))
    assert client.get(url, headers=auth).json()["relay_available"] is False
    client.app.state.relay._publisher = None
    assert client.get(url, headers=auth).json()["relay_available"] is True
    _use(client, None)
    assert client.get(url, headers=auth).json()["relay_available"] is False


def test_the_default_relay_is_carnivore_and_the_viewer_base_is_derived():
    from src.config.relay import DEFAULT_RELAY_PUBLISH_URL, RelayConfig, viewer_base_url

    assert DEFAULT_RELAY_PUBLISH_URL == "wss://relay.carnivore.ai/publish"
    assert RelayConfig().url == DEFAULT_RELAY_PUBLISH_URL
    assert viewer_base_url(RelayConfig().url) == "https://relay.carnivore.ai"
    assert viewer_base_url("wss://h.test:8443/pre/publish") == "https://h.test:8443/pre"


def test_a_v2_mint_uses_the_link_id_derived_for_this_device(client, auth, store):
    from src.core.relay_identity.publish_auth import LegacyAuth

    class _DeviceIdentity(LegacyAuth):
        def new_link_identity(self):
            return "derivedLinkIdForDevice", "bm9uY2Vub25jZW5vbmNlAA"

    client.app.state.relay.publisher._auth = _DeviceIdentity("unused")
    minted = _mint(client, auth, ttl_seconds=600).json()
    assert minted["id"] == "derivedLinkIdForDevice"
    assert minted["url"].startswith("https://relay.example.test/s/derivedLinkIdForDevice#v2.")
    rows = client.portal.call(store.live_relay_declarations)
    assert [(lid, nonce) for lid, _s, _d, nonce, _e, _k in rows] == [
        ("derivedLinkIdForDevice", "bm9uY2Vub25jZW5vbmNlAA")]
    token = minted["url"].split("#v2.", 1)[1]
    keys = derive_link_keys(token, "derivedLinkIdForDevice")
    assert rows[0][2] == keys.verifier and rows[0][5] == keys.content_key
    assert rows[0][2] != hashlib.sha256(token.encode()).hexdigest()


def test_a_revoked_publisher_says_so_in_the_refusal(client, auth):
    publisher = _publisher(False)
    publisher._status = "relay access revoked"
    _use(client, publisher)
    refused = _mint(client, auth, ttl_seconds=600)
    assert refused.status_code == 503
    assert refused.json()["detail"] == {"code": "relay_unavailable",
                                        "reason": "relay access revoked"}


def test_a_first_mint_on_a_quiet_install_starts_the_publisher(client, auth):
    publisher = _publisher(True)
    starts = []
    lifecycle = client.app.state.relay
    lifecycle._publisher = None
    lifecycle._start = lambda: starts.append(1) or publisher
    minted = _mint(client, auth, ttl_seconds=600)
    assert minted.status_code == 200, minted.text
    assert starts == [1] and lifecycle.publisher is publisher


def test_a_first_mint_whose_publisher_never_connects_is_a_503(client, auth):
    from src.core.relay_identity.publish_auth import LegacyAuth
    from src.core.relay_lifecycle import RelayLifecycle

    class _Never:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, *exc):
            return False

    async def credentials():
        return LegacyAuth("t")

    async def declarations():
        return []

    built = []

    def start():
        publisher = RelayPublisher(
            url=RELAY_PUBLISH_URL, credentials=credentials, registry=None,
            declarations=declarations, connector=lambda url, dial: _Never())
        publisher.start()
        built.append(publisher)
        return publisher

    store = client.app.state.spectator_links

    async def has_live_links() -> bool:
        return bool(await store.live_expiry_by_session())

    lifecycle = RelayLifecycle(start=start, has_live_links=has_live_links,
                               connect_timeout=0.2)
    client.app.state.relay = lifecycle
    refused = _mint(client, auth, ttl_seconds=600)
    assert refused.status_code == 503, refused.text
    assert refused.json()["detail"] == {
        "code": "relay_unavailable", "reason": "the relay publisher is not connected"}
    assert "url" not in refused.text
    client.portal.call(_awaited, lifecycle._stop_task)
    listed = client.get(
        f"/api/v1/sessions/{SESSION_ID}/spectator-links", headers=auth).json()
    assert listed["links"] == []
    assert len(built) == 1 and built[0]._task.done() and lifecycle.publisher is None




def test_the_install_wide_routes_need_the_owners_token(client):
    assert client.get("/api/v1/spectator-links").status_code == 401
    assert client.delete("/api/v1/spectator-links").status_code == 401


def test_revoke_all_ends_every_link_on_every_session_and_serves_no_token(client, auth):
    first = _mint(client, auth, SESSION_ID, ttl_seconds=600).json()
    second = _mint(client, auth, OTHER_SESSION_ID, ttl_seconds=600).json()
    listed = client.get("/api/v1/spectator-links", headers=auth)
    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()["links"]} == {first["id"], second["id"]}
    assert all(row["url"] is None for row in listed.json()["links"])
    assert first["url"].split("#", 1)[1] not in listed.text

    ended = client.delete("/api/v1/spectator-links", headers=auth)
    assert ended.status_code == 200 and set(ended.json()["ids"]) == {first["id"], second["id"]}
    assert client.get("/api/v1/spectator-links", headers=auth).json()["links"] == []
    for session_id in (SESSION_ID, OTHER_SESSION_ID):
        rows = client.get(f"/api/v1/sessions/{session_id}/spectator-links", headers=auth).json()["links"]
        assert rows == []
    assert client.delete("/api/v1/spectator-links", headers=auth).json() == {"ids": []}


def test_revoke_all_wakes_the_publisher_so_watchers_are_cut_now(client, auth, monkeypatch):
    publisher = _publisher(True)
    pokes = []
    monkeypatch.setattr(publisher, "poke", lambda: pokes.append(1))
    _use(client, publisher)
    _mint(client, auth, SESSION_ID, ttl_seconds=600)
    pokes.clear()
    assert client.delete("/api/v1/spectator-links", headers=auth).status_code == 200
    assert pokes, "the publisher was not poked after the bulk revoke"
