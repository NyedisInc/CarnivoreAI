
from __future__ import annotations

import asyncio
import contextlib
import os
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_crp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_crp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import resource_push
from src.core.catalog import index_refresher
from src.core.catalog.index_freshness import SCHEDULED_REFRESH_SECONDS
from src.core.catalog.index_refresher import FAILURE_BASE_SECONDS, IndexRefresher, next_wait
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.resource_push import topics
from src.core.skills.ledger import InstallLedger
from tests.helpers.catalog_app import catalog_app
from tests.helpers.catalog_surface import (
    build_skill,
    fixture_trust_root,
    item_for,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.test_install_ledger import make_item

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

PUBLISHER, NAME = "alex", "sme"


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


@pytest.fixture
def pushed(monkeypatch):
    seen = []
    monkeypatch.setattr(resource_push, "notify", seen.append)
    return seen


def _publish(tmp_path, served, keys, serial):
    index_kp, publisher_kp, _ = keys
    package = build_skill(tmp_path, publisher=PUBLISHER, name=NAME)
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME)], serial=serial,
    )
    return fixture_trust_root(index_kp, publisher_kp)


def test_listing_never_fetches_the_remote_index(tmp_path, served, keys, pushed):
    trust = _publish(tmp_path, served, keys, 1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        first = app.client.get("/catalog/items")
        app.clock.advance(10_000.0)
        second = app.client.get("/catalog/items")
        fetches = app.index_fetches()

    assert fetches == 0
    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == []


def test_screen_open_refresh_is_debounced_to_one_round_trip_per_five_minutes(
    tmp_path, served, keys, pushed
):
    trust = _publish(tmp_path, served, keys, 1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answers = [app.client.post("/catalog/refresh").json() for _ in range(5)]
        within = app.index_fetches()
        app.clock.advance(301.0)
        later = app.client.post("/catalog/refresh").json()
        after = app.index_fetches()
        listed = app.client.get("/catalog/items").json()

    assert [a["refreshed"] for a in answers] == [True, False, False, False, False]
    assert within == 1
    assert later["refreshed"] is True and after == 2
    assert [item["id"] for item in listed["items"]] == [f"{PUBLISHER}/{NAME}"]


def test_unchanged_refresh_publishes_nothing_and_a_changed_one_publishes_once(
    tmp_path, served, keys, pushed
):
    trust = _publish(tmp_path, served, keys, 1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.post("/catalog/refresh")
        assert pushed == [topics.CATALOG], "the first load is a change from nothing"

        app.clock.advance(301.0)
        app.client.post("/catalog/refresh")
        assert app.index_fetches() == 2
        assert pushed == [topics.CATALOG], "an unchanged index publishes nothing"

        _publish(tmp_path, served, keys, 2)
        app.clock.advance(301.0)
        app.client.post("/catalog/refresh")
        assert pushed == [topics.CATALOG, topics.CATALOG], "a new serial publishes once"


def test_a_refusal_publishes_once_not_on_every_repeat(tmp_path, served, keys, pushed):
    trust = _publish(tmp_path, served, keys, 1)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        app.client.post("/catalog/refresh")
        del pushed[:]
        index = next(served.rglob("*.json"))
        index.unlink()
        for _ in range(3):
            app.clock.advance(301.0)
            app.client.post("/catalog/refresh")
        refusal = app.client.get("/catalog/index/status").json()["refusal"]

    assert refusal is not None
    assert pushed == [topics.CATALOG], "the refusal appears once; repeats are the same content"


def test_ledger_writes_name_the_catalog_topic(tmp_path, pushed):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with contextlib.closing(connect(db_path_for(tmp_path))) as conn:
        ledger = InstallLedger(conn)
        ledger.insert(make_item(install_id="i1"))
        assert pushed == [topics.CATALOG]
        ledger.update("i1", expected_revision=1, now="2026-10-01T00:00:00Z", version="1.1.0")
        assert pushed == [topics.CATALOG] * 2
        assert ledger.delete("i1") is True
        assert ledger.delete("i1") is False
        assert pushed == [topics.CATALOG] * 3, "deleting nothing publishes nothing"


def test_the_catalog_topic_is_advertised():
    assert topics.CATALOG in topics.RESOURCE_TOPICS




def test_backoff_doubles_to_the_period_and_success_resets():
    assert next_wait(0, jitter=1.0) == SCHEDULED_REFRESH_SECONDS
    assert next_wait(1, jitter=1.0) == FAILURE_BASE_SECONDS
    assert next_wait(2, jitter=1.0) == FAILURE_BASE_SECONDS * 2
    assert next_wait(20, jitter=1.0) == SCHEDULED_REFRESH_SECONDS


def _stub_cache(outcomes):
    calls = []

    async def refresh_if_due():
        calls.append(1)
        refusal = outcomes[min(len(calls), len(outcomes)) - 1]
        return SimpleNamespace(refusal=refusal), True

    return SimpleNamespace(refresh_if_due=refresh_if_due), calls


def test_the_schedule_is_jittered_backs_off_and_recovers():

    async def scenario():
        waits = []
        cache, calls = _stub_cache([object(), object(), None])

        class Stop(Exception):
            pass

        async def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 5:
                raise Stop

        refresher = IndexRefresher(cache, sleep=sleep, rng=random.Random(7))
        with pytest.raises(Stop):
            await refresher._run()
        return waits, len(calls), refresher.failures

    waits, passes, failures = asyncio.run(scenario())
    low, high = index_refresher.FIRST_RUN_DELAY_RANGE
    assert low <= waits[0] <= high
    jlo, jhi = index_refresher.JITTER_RANGE
    assert FAILURE_BASE_SECONDS * jlo <= waits[1] <= FAILURE_BASE_SECONDS * jhi
    assert FAILURE_BASE_SECONDS * 2 * jlo <= waits[2] <= FAILURE_BASE_SECONDS * 2 * jhi
    assert SCHEDULED_REFRESH_SECONDS * jlo <= waits[3] <= SCHEDULED_REFRESH_SECONDS * jhi
    assert passes == 4
    assert failures == 0


def test_start_runs_one_task_and_stop_cancels_it():

    async def scenario():
        cache, _ = _stub_cache([None])
        gate = asyncio.Event()

        async def sleep(_seconds):
            await gate.wait()

        refresher = IndexRefresher(cache, sleep=sleep)
        refresher.start()
        first = refresher._task
        refresher.start()
        same = refresher._task is first
        await refresher.stop()
        return same, first.done()

    assert asyncio.run(scenario()) == (True, True)
