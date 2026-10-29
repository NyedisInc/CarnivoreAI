
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fbo_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fbo_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

FIELD = "foot_bar_order"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def test_absent_stays_none_and_is_a_known_field(store, config_path):
    assert FIELD in ui_preferences.known_fields()
    assert store.update({"theme": "matrix"}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert FIELD not in stored


def test_a_full_permutation_round_trips_in_the_order_written(store, config_path):
    order = ["window_7d", "context", "window_5h"]
    assert store.update({FIELD: order}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert stored[FIELD] == order


@pytest.mark.parametrize(
    "bad",
    [
        ["context", "window_5h"],
        ["context", "window_5h", "window_7d", "model"],
        ["context", "context", "window_5h"],
        ["context", "window_5h", "bogus"],
        "context",
    ],
)
def test_anything_but_a_complete_permutation_is_refused(store, config_path, bad):
    before = config_path.read_text()
    assert store.update({FIELD: bad}).status == REJECTED_INVALID
    assert config_path.read_text() == before
