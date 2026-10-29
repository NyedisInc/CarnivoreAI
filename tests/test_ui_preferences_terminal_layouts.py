
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.preferences_routes import router as preferences_router
from src.core import ui_preferences
from src.core.ui_preferences_store import (
    COMMITTED,
    REJECTED_INVALID,
    UiPreferencesStore,
)

FIELD = "terminal_layouts"
LAYOUT = {"v": 6, "rows": [{"id": "r1"}], "hidden": [], "heroCollapsed": False, "collapsed": []}


def entry(tabs=None, layout=LAYOUT):
    return {
        "layout": layout,
        "groups": {"terminal:@primary": {"tabs": tabs or ["terminal:@primary", "terminal:ses_b"]}},
    }


def arrangement(**sessions):
    return {"v": 1, "sessions": sessions or {"cloude_api:1758000000": entry()}}


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


def test_absent_stays_none_on_a_fresh_block_and_after_another_write(store, config_path):
    assert FIELD not in store.read()["values"]
    assert store.update({"theme": "matrix"}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert FIELD not in stored
    assert ui_preferences.UiPreferenceValues().terminal_layouts is None


def test_a_good_arrangement_commits_and_reads_back_typed(store):
    result = store.update({FIELD: arrangement()})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == arrangement()
    bare = store.update({FIELD: arrangement(**{"cloude_x": {"layout": None, "groups": {}}})})
    assert bare.status == COMMITTED, bare.detail


def test_unset_returns_the_field_to_absent(store):
    store.update({FIELD: arrangement()})
    assert FIELD not in store.update({FIELD: None}).values


def _many(count):
    return {"v": 1, "sessions": {f"cloude_{n}": entry() for n in range(count)}}


@pytest.mark.parametrize(
    "value",
    [
        "not an object",
        {"v": 1, "sessions": {}, "unexpected": 1},
        _many(ui_preferences.MAX_TERMINAL_LAYOUTS + 1),
        arrangement(**{"": entry()}),
        arrangement(**{"k" * 129: entry()}),
        arrangement(k=entry(tabs=["ses_b"])),
        arrangement(k=entry(tabs=["page:0123456789ABCDEF"])),
        arrangement(k=entry(tabs=["page:0123"])),
        arrangement(k=entry(tabs=["page:0123456789abcdef0"])),
        arrangement(k={"layout": LAYOUT, "groups": {"page:0123456789abcdef": {"tabs": []}}}),
        arrangement(k=entry(tabs=["widget:"])),
        arrangement(k=entry(tabs=["widget:Core.Tasks"])),
        arrangement(k=entry(tabs=["widget:.core"])),
        arrangement(k=entry(tabs=["widget:core tasks"])),
        arrangement(k=entry(tabs=["widget:a" + "b" * 64])),
        arrangement(k={"layout": LAYOUT, "groups": {"widget:core.tasks": {"tabs": []}}}),
        arrangement(k=entry(tabs=["terminal:" + "x" * 121])),
        arrangement(k=entry(tabs=[f"terminal:s{n}" for n in range(ui_preferences.MAX_TABS_PER_GROUP + 1)])),
        arrangement(k={"layout": LAYOUT, "groups": {"bad": {"tabs": []}}}),
        arrangement(k={"layout": LAYOUT, "groups": {f"terminal:g{n}": {"tabs": []} for n in range(65)}}),
        arrangement(k={"layout": {"v": "6", "rows": [{}]}, "groups": {}}),
        arrangement(k={"layout": {"v": 6, "rows": []}, "groups": {}}),
        arrangement(k={"layout": {"v": 6, "rows": [{"pad": "x" * ui_preferences.MAX_LAYOUT_BYTES}]}, "groups": {}}),
        arrangement(k={"layout": LAYOUT, "groups": {}, "active": {}}),
    ],
)
def test_a_bad_arrangement_is_refused_and_nothing_is_written(store, config_path, value):
    before = config_path.read_text()
    result = store.update({FIELD: value})
    assert result.status == REJECTED_INVALID
    assert config_path.read_text() == before


def test_every_bound_accepts_its_exact_limit(store):
    at_cap = _many(ui_preferences.MAX_TERMINAL_LAYOUTS)
    assert store.update({FIELD: at_cap}).status == COMMITTED
    tabs = [f"terminal:s{n}" for n in range(ui_preferences.MAX_TABS_PER_GROUP)]
    assert store.update({FIELD: arrangement(k=entry(tabs=tabs))}).status == COMMITTED


def test_the_whole_field_is_bounded(store, config_path):
    big = {"v": 6, "rows": [{"pad": "x" * 15000}]}
    value = {"v": 1, "sessions": {f"s{n}": {"layout": big, "groups": {}} for n in range(32)}}
    before = config_path.read_text()
    assert store.update({FIELD: value}).status == REJECTED_INVALID
    assert config_path.read_text() == before


def test_a_stale_write_is_a_409_carrying_revision_and_the_current_arrangement(client):
    theirs = arrangement(**{"cloude_api:1": entry(tabs=["terminal:@primary", "terminal:ses_c"])})
    first = client.patch("/api/v1/preferences", json={"changes": {FIELD: theirs}, "expected_revision": 0})
    assert first.status_code == 200
    mine = arrangement(**{"cloude_api:1": entry()})
    stale = client.patch("/api/v1/preferences", json={"changes": {FIELD: mine}, "expected_revision": 0})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["revision"] == 1
    assert detail["values"][FIELD] == theirs
    assert client.get("/api/v1/preferences").json()["values"][FIELD] == theirs


V7 = {
    "v": 7,
    "variants": {"wide": {"root": {
        "t": "split", "id": "s1", "dir": "h", "unit": "fr", "sizes": [0.5, 0.5],
        "children": [{"t": "leaf", "id": "terminal:@primary"}, {"t": "leaf", "id": "terminal:ses_b"}],
    }}},
    "hidden": [], "collapsed": [], "heroCollapsed": False,
}


def test_a_v7_split_tree_commits_and_reads_back_unchanged(store):
    result = store.update({FIELD: arrangement(**{"cloude_api:1": entry(layout=V7)})})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["sessions"]["cloude_api:1"]["layout"] == V7


@pytest.mark.parametrize("bad", [
    dict(V7, variants={"wide": {"root": {"t": "split", "id": "s1", "dir": "h", "unit": "fr",
                                         "sizes": [1.0], "children": [{"t": "leaf", "id": "terminal:a"}]}}}),
    dict(V7, variants={}),
    dict(V7, rows=[{"id": "r1"}]),
])
def test_a_malformed_v7_tree_is_refused(store, config_path, bad):
    result = store.update({FIELD: arrangement(**{"cloude_api:1": entry(layout=bad)})})
    assert result.status == REJECTED_INVALID
    assert FIELD not in json.loads(config_path.read_text()).get("ui_preferences", {}).get("values", {})


def test_a_page_tab_commits_beside_a_session_tab_and_a_split_out_page_component(store):
    page = "page:0123456789abcdef"
    value = arrangement(
        k={
            "layout": LAYOUT,
            "groups": {
                "terminal:@primary": {"tabs": ["terminal:@primary", page]},
                "terminal:pg-fedcba9876543210": {"tabs": ["page:fedcba9876543210"]},
            },
        }
    )
    result = store.update({FIELD: value})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == value


def test_a_widget_tab_commits_beside_session_and_page_tabs(store):
    longest = "widget:a" + "b" * 63
    value = arrangement(
        k={
            "layout": LAYOUT,
            "groups": {
                "terminal:@primary": {
                    "tabs": ["terminal:@primary", "page:0123456789abcdef", "widget:core.tasks", "widget:core.tasks-all", longest]
                },
            },
        }
    )
    result = store.update({FIELD: value})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == value
