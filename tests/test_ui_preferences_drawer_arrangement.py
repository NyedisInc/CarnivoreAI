
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_da_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_da_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.preferences_routes import router as preferences_router
from src.core import ui_preferences
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

FIELD = "drawer_arrangement"
U1 = "57eef513-b456-4dba-8e5f-1acebde60c78"
U2 = "dc491ea8-3c79-435b-8003-48c57f87b10f"


def arrangement(**over):
    value = {
        "v": 1,
        "pinned": [U1],
        "order": [U2, U1],
        "bands": {"g:grp-1": [U2], "p:7": [U1], "rogue": [], "terminals": [U2]},
        "collapsed": ["other", "g:grp-1", "p:7", "terminals"],
        "projects_open": False,
    }
    value.update(over)
    return value


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
    assert store.update({"theme": "matrix"}).status == COMMITTED
    stored = json.loads(config_path.read_text())["ui_preferences"]["values"]
    assert FIELD not in stored
    assert ui_preferences.UiPreferenceValues().drawer_arrangement is None


def test_a_good_arrangement_commits_and_reads_back(store):
    result = store.update({FIELD: arrangement()})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == arrangement()


def test_an_empty_arrangement_is_a_real_answer(store):
    empty = {"v": 1, "pinned": [], "order": [], "bands": {}, "collapsed": [], "projects_open": None}
    result = store.update({FIELD: empty})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD] == empty


def test_a_repeated_uuid_keeps_its_first_position(store):
    result = store.update({FIELD: arrangement(pinned=[U1, U2, U1])})
    assert result.values[FIELD]["pinned"] == [U1, U2]


@pytest.mark.parametrize(
    "value",
    [
        "not an object",
        arrangement(unexpected=1),
        arrangement(pinned=["carnivore_api"]),
        arrangement(order=["cloude_api"]),
        arrangement(bands={"g:grp-1": ["carnivore_api"]}),
        arrangement(pinned=[f"u{n}" for n in range(ui_preferences.MAX_REMEMBERED + 1)]),
        arrangement(bands={"pinned": [U1]}),
        arrangement(bands={"other": [U1]}),
        arrangement(bands={"nope": [U1]}),
        arrangement(bands={f"g:{n}": [] for n in range(ui_preferences.MAX_FOLDS + 1)}),
        arrangement(collapsed=["nope"]),
        arrangement(collapsed=["g:"]),
        arrangement(collapsed=["layout:"]),
        arrangement(collapsed=["c:"]),
        arrangement(collapsed=["c:abc"]),
        arrangement(collapsed=["c:1:2"]),
        arrangement(projects_open="maybe"),
        arrangement(mobile={"collapsed": ["nope"]}),
        arrangement(mobile={"collapsed": ["other"], "extra": 1}),
        arrangement(mobile={"collapsed": [f"p:{n}" for n in range(ui_preferences.MAX_FOLDED_SECTIONS + 1)]}),
        arrangement(mobile="folded"),
    ],
)
def test_a_bad_arrangement_is_refused_and_nothing_is_written(store, config_path, value):
    before = config_path.read_text()
    assert store.update({FIELD: value}).status == REJECTED_INVALID
    assert config_path.read_text() == before


def test_a_per_layout_fold_key_is_accepted(store):
    result = store.update(
        {FIELD: arrangement(collapsed=["layout:11111111-1111-4111-8111-111111111111"])}
    )
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["collapsed"] == ["layout:11111111-1111-4111-8111-111111111111"]


def test_company_fold_keys_are_accepted_and_a_stale_projects_open_is_ignored(store):
    folds = ["c:7", "c:orphaned", "p:3"]
    result = store.update({FIELD: arrangement(collapsed=folds, projects_open=False)})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["collapsed"] == folds


def test_a_computer_switched_off_is_a_fold_key_on_both_device_lists(store):
    key = "host-off:ea8be107-7c96-46ef-8c06-76cea92f42fa"
    result = store.update({FIELD: arrangement(collapsed=[key], mobile={"collapsed": [key]})})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["collapsed"] == [key]
    assert store.update({FIELD: arrangement(collapsed=["host-off:"])}).status == REJECTED_INVALID


@pytest.mark.parametrize("bad", ["c:1\n", "c:", "c:x", "c:-1"])
def test_a_malformed_company_fold_key_is_rejected(store, bad):
    assert store.update({FIELD: arrangement(collapsed=[bad])}).status == REJECTED_INVALID


def test_every_bound_accepts_its_exact_limit(store):
    at_cap = [f"u{n}" for n in range(ui_preferences.MAX_REMEMBERED)]
    assert store.update({FIELD: arrangement(pinned=at_cap, order=at_cap)}).status == COMMITTED
    bands = {f"g:{n}": [] for n in range(ui_preferences.MAX_FOLDS)}
    assert store.update({FIELD: arrangement(bands=bands)}).status == COMMITTED


def test_the_whole_field_is_bounded(store, config_path):
    uuids = [f"{n:04d}" + "a" * 60 for n in range(ui_preferences.MAX_REMEMBERED)]
    bands = {f"g:{n}": uuids for n in range(ui_preferences.MAX_FOLDS)}
    before = config_path.read_text()
    assert store.update({FIELD: arrangement(bands=bands)}).status == REJECTED_INVALID
    assert config_path.read_text() == before


def test_a_stale_write_is_a_409_carrying_revision_and_the_current_arrangement(client):
    theirs = arrangement(pinned=[U2])
    first = client.patch("/api/v1/preferences", json={"changes": {FIELD: theirs}, "expected_revision": 0})
    assert first.status_code == 200
    stale = client.patch(
        "/api/v1/preferences", json={"changes": {FIELD: arrangement()}, "expected_revision": 0}
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["revision"] == 1
    assert detail["values"][FIELD] == theirs
    assert client.get("/api/v1/preferences").json()["values"][FIELD] == theirs


def test_a_cascade_sized_fold_list_is_accepted(store):
    keys = [f"p:{n}" for n in range(ui_preferences.MAX_FOLDED_SECTIONS)]
    assert store.update({FIELD: arrangement(collapsed=keys)}).status == COMMITTED
    assert store.update({FIELD: arrangement(collapsed=keys + ["p:over"])}).status == REJECTED_INVALID


def test_a_phone_view_commits_reads_back_and_dedupes(store):
    mobile = {"collapsed": ["other", "c:1", "ledger_hidden", "other"]}
    result = store.update({FIELD: arrangement(mobile=mobile)})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["mobile"] == {"collapsed": ["other", "c:1", "ledger_hidden"]}
    assert result.values[FIELD]["collapsed"] == arrangement()["collapsed"], "the desktop list is untouched"


def test_an_old_shape_value_has_no_mobile_key_and_round_trips(store):
    result = store.update({FIELD: arrangement()})
    assert "mobile" not in result.values[FIELD]


def test_a_write_that_omits_mobile_keeps_the_stored_phone_view(store):
    store.update({FIELD: arrangement(mobile={"collapsed": ["c:1"]})})
    result = store.update({FIELD: arrangement(collapsed=["other"])})
    assert result.status == COMMITTED, result.detail
    assert result.values[FIELD]["collapsed"] == ["other"]
    assert result.values[FIELD]["mobile"] == {"collapsed": ["c:1"]}


def test_a_write_that_names_mobile_replaces_it_and_null_clears_it(store):
    store.update({FIELD: arrangement(mobile={"collapsed": ["c:1"]})})
    replaced = store.update({FIELD: arrangement(mobile={"collapsed": []})})
    assert replaced.values[FIELD]["mobile"] == {"collapsed": []}
    cleared = store.update({FIELD: arrangement(mobile=None)})
    assert cleared.values[FIELD]["mobile"] is None


def test_apply_changes_carries_mobile_only_for_the_drawer_field():
    stored = {"drawer_arrangement": {"v": 1, "mobile": {"collapsed": ["c:1"]}}}
    config = {ui_preferences.UI_PREFERENCES_KEY: {"schema_version": ui_preferences.SCHEMA_VERSION, "revision": 1, "values": stored}}
    _, block, _ = ui_preferences.apply_changes(config, {"drawer_arrangement": {"v": 1, "pinned": []}})
    assert block["values"]["drawer_arrangement"]["mobile"] == {"collapsed": ["c:1"]}


SECTIONS_NON_DEFAULT = ["browsers", "review", "pack", "terminals", "rogue", "companies", "groups", "layouts", "pinned"]


def test_section_order_is_stored_validated_and_kept_by_a_write_that_omits_it(store):
    result = store.update({FIELD: arrangement(sections=SECTIONS_NON_DEFAULT)})
    assert result.status == COMMITTED, result.detail
    stored = result.values[FIELD]["sections"]
    assert len(stored) == 9, "population: all nine ids read back"
    assert stored == SECTIONS_NON_DEFAULT

    kept = store.update({FIELD: arrangement(collapsed=["other"])})
    assert kept.status == COMMITTED, kept.detail
    assert kept.values[FIELD]["sections"] == SECTIONS_NON_DEFAULT, "a write that omits the key keeps the order"

    for bad in (["pinned", "nope"], ["pinned", "pinned"]):
        refused = store.update({FIELD: arrangement(sections=bad)})
        assert refused.status == REJECTED_INVALID
        assert "section" in refused.detail
    assert store.update({FIELD: arrangement(collapsed=["other"])}).values[FIELD]["sections"] == SECTIONS_NON_DEFAULT

    cleared = store.update({FIELD: arrangement(sections=None)})
    assert cleared.status == COMMITTED, cleared.detail
    assert cleared.values[FIELD]["sections"] is None
