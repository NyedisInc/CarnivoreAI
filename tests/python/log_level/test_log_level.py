
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_loglevel_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_loglevel_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import log_level_routes
from src.api.auth import require_auth
from src.core.log_level import live, store


@pytest.fixture(autouse=True)
def restore_level():
    root = logging.getLogger().level
    before = live.current_number()
    yield
    live.apply_level(live.name_for_number(before))
    logging.getLogger().setLevel(root)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"keep": 1}))
    monkeypatch.setattr(log_level_routes, "_config_path", lambda: config)
    monkeypatch.setattr(log_level_routes, "_env_level", lambda: "info")
    live.apply_level("info")
    app = FastAPI()
    app.include_router(log_level_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return type("W", (), {"client": TestClient(app), "config": config, "app": app})()


def test_get_defaults_to_env_info(world):
    got = world.client.get("/log-level").json()
    assert got == {"level": "info", "source": "env", "env_level": "info",
                   "choices": ["error", "warn", "info", "debug"], "expires_at": None}


def test_put_round_trip_applies_live_and_persists(world):
    got = world.client.put("/log-level", json={"level": "warn"}).json()
    assert got["level"] == "warn" and got["source"] == "setting"
    assert live.current_number() == logging.WARNING
    assert logging.getLogger().level == logging.WARNING
    doc = json.loads(world.config.read_text())
    assert doc["log_level"] == "warn" and doc["keep"] == 1
    assert world.client.get("/log-level").json()["level"] == "warn"


def test_put_null_goes_back_to_env(world):
    world.client.put("/log-level", json={"level": "error"})
    got = world.client.put("/log-level", json={"level": None}).json()
    assert got["level"] == "info" and got["source"] == "env"
    assert "log_level" not in json.loads(world.config.read_text())


@pytest.mark.parametrize("body", [{"level": "loud"}, {"level": "WARNING"}, {}, {"level": "info", "x": 1}])
def test_put_rejects_bad_bodies_and_changes_nothing(world, body):
    assert world.client.put("/log-level", json=body).status_code == 422
    assert live.current_number() == logging.INFO
    assert "log_level" not in json.loads(world.config.read_text())


def test_put_with_missing_config_is_500_and_level_unchanged(world):
    world.config.unlink()
    assert world.client.put("/log-level", json={"level": "warn"}).status_code == 500
    assert live.current_number() == logging.INFO


def test_every_route_requires_auth(world):
    world.app.dependency_overrides.clear()
    client = TestClient(world.app)
    assert client.get("/log-level").status_code in (401, 403)
    assert client.put("/log-level", json={"level": "debug"}).status_code in (401, 403)


def test_boot_rule_choice_then_env_then_info(tmp_path):
    path = tmp_path / "config.json"
    assert store.effective_name("DEBUG", path) == "debug"
    path.write_text("{not json")
    assert store.effective_name("WARNING", path) == "warn"
    assert store.effective_name("nonsense", path) == "info"
    path.write_text(json.dumps({"log_level": "error"}))
    assert store.effective_name("DEBUG", path) == "error"
    path.write_text(json.dumps({"log_level": "loud"}))
    assert store.effective_name("DEBUG", path) == "debug"


def test_persisted_choice_is_applied_at_boot(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    store.set_chosen(path, "debug")
    live.apply_level(store.effective_name("INFO", path))
    assert live.current_number() == logging.DEBUG


def test_set_chosen_is_a_noop_when_unchanged(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    assert store.set_chosen(path, "warn") is True
    assert store.set_chosen(path, "warn") is False
    assert store.set_chosen(path, None) is True
    assert store.set_chosen(path, None) is False


def test_debug_event_appears_only_after_switching_to_debug():
    saved = structlog.get_config()
    sink: list = []

    class Sink:

        def msg(self, message):
            sink.append(json.loads(message))

        debug = info = warning = error = critical = exception = msg

    structlog.configure(
        processors=[structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
        wrapper_class=live.LiveLevelBoundLogger,
        logger_factory=lambda *_a: Sink(),
        cache_logger_on_first_use=True,
    )
    try:
        bound = structlog.get_logger().bind(who="poller")
        live.apply_level("info")
        bound.debug("quiet_event")
        bound.info("loud_event")
        assert [e["event"] for e in sink] == ["loud_event"]
        live.apply_level("debug")
        bound.debug("quiet_event")
        assert [e["event"] for e in sink] == ["loud_event", "quiet_event"]
        live.apply_level("error")
        bound.warning("warn_event")
        bound.error("error_event")
        bound.exception("exc_event")
        assert [e["event"] for e in sink][2:] == ["error_event", "exc_event"]
        assert bound.is_enabled_for(logging.ERROR) and not bound.is_enabled_for(logging.WARNING)
    finally:
        structlog.configure(**{k: v for k, v in saved.items()})


def test_normalize_spellings():
    assert live.normalize(" Warning ") == "warn"
    assert live.normalize("CRITICAL") == "error"
    assert live.normalize(5) is None and live.normalize("x") is None
