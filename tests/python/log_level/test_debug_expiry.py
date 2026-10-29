
from __future__ import annotations

import json
import logging
import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import log_level_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.log_level import expiry, live  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    root = logging.getLogger().level
    live.apply_level("info")
    expiry.clear()
    yield
    expiry.clear()
    live.apply_level("info")
    logging.getLogger().setLevel(root)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"keep": 1}))
    monkeypatch.setattr(log_level_routes, "_config_path", lambda: config)
    monkeypatch.setattr(log_level_routes, "_env_level", lambda: "info")
    monkeypatch.setattr(log_level_routes, "_env_name_raw", lambda: "info")
    app = FastAPI()
    app.include_router(log_level_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as tc:
        tc.config = config
        yield tc


def test_debug_defaults_to_1800_and_is_not_stored(client):
    before = time.time()
    got = client.put("/log-level", json={"level": "debug"}).json()
    assert got["level"] == "debug" and got["expires_at"]
    left = expiry.expires_at() - before
    assert 1795 <= left <= 1801
    assert "log_level" not in json.loads(client.config.read_text())
    assert client.get("/log-level").json()["expires_at"] == got["expires_at"]


def test_expiry_is_capped(client):
    client.put("/log-level", json={"level": "debug", "expires_in_s": 99999})
    assert expiry.expires_at() - time.time() <= expiry.MAX_DEBUG_SECONDS + 1


def test_debug_reverts_to_previous_level_after_expiry(client):
    client.put("/log-level", json={"level": "warn"})
    client.put("/log-level", json={"level": "debug", "expires_in_s": 1})
    assert live.current_number() == logging.DEBUG
    time.sleep(1.4)
    assert live.current_number() == logging.WARNING
    assert client.get("/log-level").json()["expires_at"] is None


def test_set_twice_latest_wins_with_one_timer_and_original_revert(client):
    client.put("/log-level", json={"level": "debug", "expires_in_s": 1})
    first = expiry._handle
    client.put("/log-level", json={"level": "debug", "expires_in_s": 3})
    assert first.cancelled() and expiry._handle is not first
    time.sleep(1.4)
    assert live.current_number() == logging.DEBUG
    expiry._expire()
    assert live.current_number() == logging.INFO
    assert expiry._handle is None and expiry.expires_at() is None


def test_non_debug_write_cancels_the_pending_revert(client):
    client.put("/log-level", json={"level": "debug", "expires_in_s": 1})
    handle = expiry._handle
    client.put("/log-level", json={"level": "error"})
    assert handle.cancelled() and expiry.expires_at() is None
    time.sleep(1.4)
    assert live.current_number() == logging.ERROR


def test_bad_expiry_is_422(client):
    assert client.put("/log-level", json={"level": "debug", "expires_in_s": 0}).status_code == 422


def test_arm_needs_no_config_file(client):
    client.config.unlink()
    assert client.put("/log-level", json={"level": "debug"}).status_code == 200


def test_clear_without_arm_is_safe():
    expiry.clear()
    assert expiry.expires_at() is None


def _config(tmp_path, doc):
    path = tmp_path / "boot.json"
    path.write_text(json.dumps(doc))
    return path


def test_saved_debug_gets_a_fresh_expiry_and_is_cleared(tmp_path, monkeypatch):
    monkeypatch.delenv(expiry.DEBUG_BOOT_ENV, raising=False)
    path = _config(tmp_path, {"log_level": "debug", "keep": 1})
    assert expiry.boot_level("INFO", path) == "debug"

    async def run():
        got = expiry.arm_at_boot("INFO", path)
        assert got[0] == "info" and expiry.expires_at() - time.time() > 1790
        assert live.current_number() == logging.DEBUG
        expiry._expire()

    import asyncio

    asyncio.run(run())
    assert "log_level" not in json.loads(path.read_text()) and live.current_number() == logging.INFO


def test_debug_boot_env_overrides_a_saved_level_without_persisting(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv(expiry.DEBUG_BOOT_ENV, "1")
    path = _config(tmp_path, {"log_level": "warn"})
    assert expiry.boot_level("INFO", path) == "debug"

    async def run():
        assert expiry.arm_at_boot("INFO", path)[0] == "warn"
        expiry._expire()

    asyncio.run(run())
    assert json.loads(path.read_text())["log_level"] == "warn"
    assert live.current_number() == logging.WARNING


def test_normal_boot_arms_nothing(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.delenv(expiry.DEBUG_BOOT_ENV, raising=False)
    path = _config(tmp_path, {"log_level": "warn"})
    assert expiry.boot_level("INFO", path) == "warn"
    assert asyncio.run(_arm(path)) is None and expiry.expires_at() is None


async def _arm(path):
    return expiry.arm_at_boot("INFO", path)
