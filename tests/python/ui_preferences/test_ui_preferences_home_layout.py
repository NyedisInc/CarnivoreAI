
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_hl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_hl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.preferences_routes import router as preferences_router
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

FIELD = "home_layout"
GRID = {"v": 6, "rows": [{"id": "r1"}], "hidden": [], "heroCollapsed": False}


def board(id="home", name="home", layout=GRID):
    return {"id": id, "name": name, "layout": layout}


def value(seed=0, layout=GRID):
    return {"v": 2, "boards": [board(layout=layout)], "analytics_seed": seed}


def single(seed=0, layout=GRID):
    return {"v": 1, "layout": layout, "analytics_seed": seed}


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


@pytest.fixture
def client(config_path: Path):
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: config_path)
    app.state.connection_manager = None
    with TestClient(app) as test_client:
        yield test_client


def test_absent_stays_absent_on_a_fresh_block_and_after_another_write(store, config_path):
    assert FIELD not in store.read()["values"]
    assert store.update({"theme": "matrix"}).status == COMMITTED
    assert FIELD not in json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert ui_preferences.UiPreferenceValues().home_layout is None
    assert FIELD in ui_preferences.known_fields()


def test_a_good_value_commits_and_reads_back(store):
    result = store.update({FIELD: value(seed=2)})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == value(seed=2)
    assert FIELD not in store.update({FIELD: None}).values


def test_the_seed_defaults_to_zero(store):
    result = store.update({FIELD: {"v": 2, "boards": [board()]}})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["analytics_seed"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        "not an object",
        {"v": 1},
        {"v": 1, "layout": GRID, "unexpected": 1},
        {"v": 2, "boards": []},
        {"v": 2, "boards": [board(), board()]},
        {"v": 2, "boards": [board(id="bad id")]},
        {"v": 2, "boards": [board(id="x" * 33)]},
        {"v": 2, "boards": [board(name="")]},
        {"v": 2, "boards": [board(name="n" * (ui_preferences.MAX_HOME_BOARD_NAME + 1))]},
        {"v": 2, "boards": [{"id": "home", "name": "home"}]},
        {"v": 2, "boards": [board()], "layout": GRID},
        {"v": 2, "boards": [board(id=f"b{i}") for i in range(ui_preferences.MAX_HOME_BOARDS + 1)]},
        value(seed=ui_preferences.MAX_ANALYTICS_SEED + 1),
        value(seed=-1),
        value(layout={"v": "6", "rows": [{}]}),
        value(layout={"v": 6, "rows": []}),
        value(layout={"v": 6}),
        value(layout={"v": 6, "rows": [{"pad": "x" * ui_preferences.MAX_LAYOUT_BYTES}]}),
    ],
)
def test_a_bad_value_is_refused(store, bad):
    assert store.update({FIELD: bad}).status == REJECTED_INVALID


def test_a_stale_write_is_a_409_carrying_the_current_value(client):
    first = client.patch("/api/v1/preferences", json={"changes": {FIELD: value(seed=1)}, "expected_revision": 0})
    assert first.status_code == 200
    stale = client.patch("/api/v1/preferences", json={"changes": {FIELD: value(seed=2)}, "expected_revision": 0})
    assert stale.status_code == 409
    body = stale.json()["detail"]
    assert body["values"][FIELD] == value(seed=1)
    assert body["revision"] >= 1


def test_the_single_grid_value_migrates_to_the_home_board_untouched(store):
    result = store.update({FIELD: single(seed=1)})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == value(seed=1)


def test_the_most_boards_commit_and_keep_their_order(store):
    boards = [board(id=f"b{i}", name=f"board {i}") for i in range(ui_preferences.MAX_HOME_BOARDS)]
    result = store.update({FIELD: {"v": 2, "boards": boards, "analytics_seed": 0}})
    assert result.status == COMMITTED, result.detail
    assert [b["id"] for b in result.values[FIELD]["boards"]] == [b["id"] for b in boards]


def test_the_total_stays_inside_the_field_cap():
    room = ui_preferences.MAX_LAYOUT_BYTES - 200
    full = {"v": 6, "rows": [{"pad": "x" * room}]}
    boards = [board(id=f"b{i}", layout=full) for i in range(ui_preferences.MAX_HOME_BOARDS)]
    model = ui_preferences.HomeLayout(boards=boards)
    assert len(json.dumps(model.model_dump(mode="json")).encode("utf-8")) <= ui_preferences.MAX_HOME_LAYOUT_BYTES
    assert ui_preferences.UiPreferenceValues(home_layout=model).home_layout is not None
