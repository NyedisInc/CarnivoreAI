
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog import client as catalog_client
from src.core.catalog.index_cache import FORCE_REFRESH_FLOOR_SECONDS, IndexCache
from src.core.catalog.index_state import IndexStateStore
from src.core.catalog.trust_root import production_trust_root
from src.core.catalog.verify_types import SIGNATURE_INVALID
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from tests.helpers.catalog_app import catalog_app
from tests.helpers.catalog_surface import (
    INDEX_PATH,
    FrozenClock,
    build_skill,
    fixture_trust_root,
    item_for,
    open_and_list,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.helpers.static_http import self_signed_cert, serve_directory

PUBLISHER = "alex"
NAME = "sme"
ITEM_ID = f"{PUBLISHER}/{NAME}"

pytestmark = pytest.mark.skipif(
    minisign_binary() is None, reason=SKIP_REASON
)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def _one_item_index(tmp_path, served, keys, *, scripts: int = 0, serial: int = 1):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(tmp_path, publisher=PUBLISHER, name=NAME)
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME, scripts=scripts)],
        serial=serial,
    )
    return fixture_trust_root(index_kp, publisher_kp)




def test_the_listing_returns_the_signed_item_with_no_install(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = open_and_list(app)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [ITEM_ID]
    assert body["items"][0]["installed"] is None
    assert body["items"][0]["untrusted"] is False
    assert body["untrusted"] == []


def test_the_list_route_serves_a_version_grade(tmp_path, served, keys):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(tmp_path, publisher=PUBLISHER, name=NAME)
    serve_archive(served, package.tar_bytes)
    grade = {
        "grade": "D",
        "checked": 12,
        "failed": [
            {
                "rule": "description.length",
                "level": "required",
                "detail": "description is 1059 characters, over the 1024 the specification allows",
            }
        ],
        "not_graded": ["compatibility.length", "metadata.shape"],
    }
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME, grade=grade)],
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = open_and_list(app).json()

    version = body["items"][0]["versions"][0]
    assert version["grade"]["grade"] == "D"
    assert version["grade"]["failed"][0]["rule"] == "description.length"


def test_the_index_block_carries_the_serial_and_the_as_of_stamp(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys, serial=9)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = open_and_list(app).json()

    assert body["index"]["serial"] == 9
    assert body["index"]["as_of"] == body["index"]["generated_at"]
    assert body["index"]["as_of"].startswith("2026-09-01")
    assert body["index"]["degraded"] is False
    assert body["index"]["refusal"] is None


def test_one_item_is_reachable_by_its_slashed_id(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.get(f"/catalog/items/{ITEM_ID}")
        missing = app.client.get("/catalog/items/alex/nothing")

    assert response.status_code == 200, response.text
    assert response.json()["item"]["name"] == NAME
    assert missing.status_code == 404


def test_an_item_signed_by_an_unpinned_key_is_listed_as_untrusted(
    tmp_path, served, keys
):
    index_kp, publisher_kp, stranger_kp = keys
    mine = build_skill(tmp_path, publisher=PUBLISHER, name=NAME, label="mine")
    theirs = build_skill(tmp_path, publisher="stranger", name="other", label="theirs")
    serve_archive(served, mine.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(mine, publisher=PUBLISHER, name=NAME)],
        serial=1,
    )
    from tests.helpers.catalog_fixture import sign_item_versions

    stranger_item = sign_item_versions(
        tmp_path,
        item_for(theirs, publisher="stranger", name="other"),
        stranger_kp,
    )
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(mine, publisher=PUBLISHER, name=NAME), stranger_item],
        serial=2,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        body = open_and_list(app).json()

    assert [item["id"] for item in body["items"]] == [ITEM_ID]
    assert [item["id"] for item in body["untrusted"]] == ["stranger/other"]
    assert body["untrusted"][0]["untrusted"] is True




def test_the_production_trust_root_refuses_this_same_good_index(
    tmp_path, served, keys
):
    _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=production_trust_root()) as app:
        response = open_and_list(app)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == SIGNATURE_INVALID


def test_a_transport_failure_with_nothing_held_is_a_502(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.server.status_overrides[f"/{INDEX_PATH}"] = 503
        response = open_and_list(app)

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "index_unavailable"




def test_a_second_read_inside_five_minutes_opens_no_socket(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        open_and_list(app)
        first = len(app.server.seen())
        open_and_list(app)
        assert len(app.server.seen()) == first

        app.clock.advance(301.0)
        open_and_list(app)
        assert len(app.server.seen()) > first


def test_a_forced_refresh_ignores_the_throttle(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        open_and_list(app)
        app.clock.advance(FORCE_REFRESH_FLOOR_SECONDS + 1.0)
        assert app.client.get("/catalog/index/status").json()["stale"] is False
        before = len(app.server.seen())
        response = app.client.post("/catalog/index/refresh")

    assert response.status_code == 200, response.text
    assert response.json()["refreshed"] is True
    assert len(app.server.seen()) > before


def test_a_burst_of_forced_refreshes_is_floored_to_one_round_trip(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        open_and_list(app)
        app.clock.advance(FORCE_REFRESH_FLOOR_SECONDS + 1.0)
        before = app.index_fetches()

        answers = [
            app.client.post("/catalog/index/refresh") for _ in range(25)
        ]
        floored = app.index_fetches()

        app.clock.advance(FORCE_REFRESH_FLOOR_SECONDS + 1.0)
        app.client.post("/catalog/index/refresh")
        released = app.index_fetches()

        assert app.client.get("/catalog/index/status").json()["refreshed"] is None

    assert all(answer.status_code == 200 for answer in answers), answers[0].text
    assert floored == before + 1, "one force went out, the other twenty four did not"
    assert answers[0].json()["refreshed"] is True
    assert answers[-1].json()["refreshed"] is False
    assert answers[-1].json()["serial"] == answers[0].json()["serial"]
    assert released == floored + 1, "past the floor a force goes out again"


def test_the_staleness_badge_is_derived_on_every_read_not_carried_by_a_304(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        fresh = app.client.get("/catalog/index/status").json()
        assert fresh["degraded"] is False, "the control: a day-old index is fresh"

        app.clock.advance(31 * 24 * 60 * 60)
        status = app.client.get("/catalog/index/status")
        listing = open_and_list(app).json()
        fetches = app.index_fetches()

    assert status.status_code == 200, status.text
    assert fetches >= 2, "the second read must actually have gone to the network"
    assert status.json()["serial"] == fresh["serial"], "the 304 kept the index"
    assert status.json()["refusal"] is None
    assert status.json()["degraded"] is True
    assert listing["index"]["degraded"] is True


def test_a_conditional_refetch_gets_a_304_and_keeps_the_snapshot(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = open_and_list(app).json()
        app.clock.advance(301.0)
        second = open_and_list(app).json()

        assert app.index_fetches() >= 2
        assert second["index"]["serial"] == first["index"]["serial"]
        assert second["items"][0]["id"] == ITEM_ID
        assert second["index"]["refusal"] is None


def _persisted_etag(state: Path, trust) -> str:
    with contextlib.closing(connect(db_path_for(state))) as conn:
        row = IndexStateStore(conn).get(trust.index_key.key_id)
    return None if row is None else row.etag


def test_a_cold_process_with_a_persisted_etag_still_ends_up_holding_an_index(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as first:
        warm = open_and_list(first).json()
    assert [item["id"] for item in warm["items"]] == [ITEM_ID], "arrange failed"
    assert _persisted_etag(tmp_path / "state", trust) is not None, (
        "the tag has to outlive the process or this proves nothing"
    )

    with catalog_app(tmp_path, served, trust_root=trust) as cold:
        response = open_and_list(cold)
        fetches = cold.index_fetches()

    assert response.status_code == 200, response.text
    body = response.json()
    assert fetches == 1, "one round trip, unconditional"
    assert [item["id"] for item in body["items"]] == [ITEM_ID]
    assert body["index"]["serial"] == warm["index"]["serial"]
    assert body["index"]["refusal"] is None


def test_a_warm_cache_still_asks_conditionally(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = open_and_list(app).json()
        app.clock.advance(301.0)
        second = open_and_list(app).json()
        index_gets = app.index_fetches()
        signature_gets = sum(
            1 for path in app.server.seen() if path.endswith(".minisig")
        )

    assert index_gets == 2, "the second read must have gone to the network"
    assert signature_gets == 1, "a 200 would have fetched the signature again"
    assert second["index"]["serial"] == first["index"]["serial"]
    assert [item["id"] for item in second["items"]] == [ITEM_ID]


def test_a_refused_refresh_keeps_the_last_good_index_and_reports_the_code(
    tmp_path, served, keys
):
    trust = _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        good = open_and_list(app).json()
        assert good["items"], "the first read must succeed or this proves nothing"

        app.server.status_overrides[f"/{INDEX_PATH}"] = 500
        app.clock.advance(301.0)
        after = open_and_list(app)

    assert after.status_code == 200, after.text
    body = after.json()
    assert [item["id"] for item in body["items"]] == [ITEM_ID]
    assert body["index"]["refusal"]["code"] == "index_unavailable"


@pytest.mark.asyncio
async def test_two_concurrent_reads_share_one_fetch(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)
    tls = tmp_path / "tls"
    tls.mkdir()
    cert = self_signed_cert(tls)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    with serve_directory(served, tls_cert=cert) as server:
        await catalog_client.init(verify=str(cert[0]))
        try:
            cache = IndexCache(
                index_url=lambda: f"{server.base_url}/{INDEX_PATH}",
                trust_root=trust,
                clock=FrozenClock(),
                open_db=lambda: connect(db_path_for(state)),
            )
            first, second = await asyncio.gather(cache.get(), cache.get())
        finally:
            await catalog_client.shutdown()

    fetches = [p for p in server.seen() if p == f"/{INDEX_PATH}"]
    assert len(fetches) == 1, server.seen()
    assert first.verified is not None
    assert second.verified is first.verified


def test_the_status_route_reports_a_refusal_as_a_field_not_a_status(
    tmp_path, served, keys
):
    _one_item_index(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=production_trust_root()) as app:
        response = app.client.get("/catalog/index/status")

    assert response.status_code == 200, response.text
    assert response.json()["refusal"]["code"] == SIGNATURE_INVALID
    assert response.json()["serial"] is None


def test_the_clock_the_cache_uses_is_the_injected_one(tmp_path, served, keys):
    trust = _one_item_index(tmp_path, served, keys)
    clock = FrozenClock()

    with catalog_app(tmp_path, served, trust_root=trust, clock=clock) as app:
        body = open_and_list(app).json()
        assert body["index"]["stale"] is False
        for _ in range(3):
            open_and_list(app)
        assert app.index_fetches() == 1
