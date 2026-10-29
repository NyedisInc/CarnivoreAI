
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

FIELD = "warroom_layout"
GRID = {"v": 6, "rows": [{"id": "r1", "kind": "flex", "size": 1, "slots": [{"id": "warroom", "fr": 1}]}], "hidden": []}


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def test_absent_stays_absent_on_a_fresh_block_and_after_another_write(store, config_path):
    assert FIELD not in store.read()["values"]
    assert store.update({"theme": "matrix"}).status == COMMITTED
    assert FIELD not in json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert ui_preferences.UiPreferenceValues().warroom_layout is None
    assert FIELD in ui_preferences.known_fields()


def test_a_good_value_commits_and_reads_back(store):
    result = store.update({FIELD: {"v": 1, "layout": GRID}})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == {"v": 1, "layout": GRID}
    assert FIELD not in store.update({FIELD: None}).values


@pytest.mark.parametrize(
    "bad",
    [
        "not an object",
        {"v": 1},
        {"v": 1, "layout": GRID, "unexpected": 1},
        {"v": 1, "layout": {"v": "6", "rows": [{}]}},
        {"v": 1, "layout": {"v": 6, "rows": []}},
        {"v": 1, "layout": {"v": 6}},
        {"v": 1, "layout": {"v": 6, "rows": [{"pad": "x" * ui_preferences.MAX_LAYOUT_BYTES}]}},
    ],
)
def test_a_bad_value_is_refused(store, bad):
    assert store.update({FIELD: bad}).status == REJECTED_INVALID
