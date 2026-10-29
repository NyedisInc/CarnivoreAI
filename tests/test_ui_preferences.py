
from __future__ import annotations

import builtins
import json
import threading
import time
from pathlib import Path

import pytest

from src.core import config_writer, ui_preferences
from src.core.ui_preferences_store import (
    COMMITTED,
    REJECTED_INVALID,
    STALE_REVISION,
    UNCHANGED,
    UiPreferencesStore,
)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}, indent=2))
    return path


@pytest.fixture
def store(config_path: Path) -> UiPreferencesStore:
    return UiPreferencesStore(lambda: config_path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())



MUST_NOT_SYNC = (
    "launchpad_deleted_sessions_visible",
    "launchpad_archived_visible",
    "status_key_open",
    "away_last_choice",
    "archive_project_order",
    "archive_panes",
    "theme_js_allowlist",
    "theme_vars",
    "audio_settings_version",
    "audio_muted",
    "sidebar_open",
)


@pytest.mark.parametrize("field", MUST_NOT_SYNC)
def test_a_per_viewer_key_is_not_a_known_preference(field: str):
    assert field not in ui_preferences.known_fields(), (
        f"'{field}' was classified as per-viewer in "
        "docs/ui-preferences-inventory.md. Syncing it pushes one device's "
        "layout onto every other device. If this is a deliberate change, "
        "the inventory has to change first."
    )


def test_a_secret_can_never_be_stored_even_as_an_unknown_field(store):
    for name in ("claude_tunnel_token", "claude_refresh_token"):
        result = store.update({name: "value"})
        assert result.status == REJECTED_INVALID
        assert name not in result.values
        assert "value" not in (result.detail or "")


@pytest.mark.parametrize(
    "name", ["some_api_key", "openrouter_token", "user_password", "my_secret"]
)
def test_a_name_that_reads_like_a_credential_is_refused(store, name: str):
    assert store.update({name: "x"}).status == REJECTED_INVALID




@pytest.mark.parametrize(
    "field", ["sidebar_pinned", "launchpad_collapsed"]
)
def test_the_shared_ambiguous_keys_are_known_preferences(field: str):
    assert field in ui_preferences.known_fields()


def test_foot_bar_items_is_a_known_preference_with_all_eight_ids():
    assert "foot_bar_items" in ui_preferences.known_fields()
    assert ui_preferences.FOOT_BAR_ITEM_IDS == (
        "model", "effort", "context", "window_5h", "window_7d", "agents", "shells", "timers",
    )


def test_foot_bar_layout_is_a_known_preference_with_three_options_per_half():
    assert "foot_bar_layout" in ui_preferences.known_fields()
    assert ui_preferences.FOOT_BAR_LAYOUT_OPTIONS == ("a", "b", "c")


@pytest.mark.parametrize("half", ["collapsed", "open"])
@pytest.mark.parametrize("option", ["a", "b", "c"])
def test_foot_bar_layout_accepts_every_built_option_per_half(half: str, option: str):
    layout = ui_preferences.FootBarLayout(**{half: option})
    assert getattr(layout, half) == option


def test_foot_bar_layout_absent_reads_as_none_both_halves():
    layout = ui_preferences.FootBarLayout()
    assert layout.collapsed is None
    assert layout.open is None




@pytest.mark.parametrize(
    "changes",
    [
        {"sidebar_density": "enormous"},
        {"sidebar_density_mobile": "enormous"},
        {"widget_drawer_view": "grid"},
        {"widget_drawer_view_mobile": 1},
        {"sidebar_show_stats": "yes"},
        {"sidebar_show_stats_mobile": 0},
        {"sidebar_layout": "docked"},
        {"sidebar_layout": True},
        {"sidebar_list_open": "yes"},
        {"sidebar_list_sleeping_mobile": 0},
        {"sidebar_show_closed": "yes"},
        {"sidebar_show_closed_mobile": 1},
        {"sidebar_hide_empty_sections": "yes"},
        {"sidebar_hide_empty_sections": 1},
        {"theme": "../../etc/passwd"},
        {"launch_last_model": "-leading-dash"},
        {"launchpad_collapsed": {"not-a-section": True}},
        {"theme_favorites": ["../x"]},
        {"theme_favorites": "matrix"},
        {"theme_favorites": ["t%d" % n for n in range(ui_preferences.MAX_THEME_FAVORITES + 1)]},
        {"animations": "no"},
        {"animations": 0},
        {"toast_mode": "loud"},
        {"toast_mode": True},
        {"terminal_screen_reader": "loud"},
        {"terminal_screen_reader": True},
        {"account_welcome_seen": "yes"},
        {"account_welcome_seen": 1},
        {"foot_bar_items": {"not-an-item": True}},
        {"foot_bar_items": {"agents": "yes"}},
        {"foot_bar_items": {"agents": 1}},
        {"foot_bar_layout": {"collapsed": "z"}},
        {"foot_bar_layout": {"open": "enormous"}},
        {"foot_bar_layout": {"unexpected": "a"}},
    ],
)
def test_a_bad_value_is_refused_and_nothing_is_written(store, config_path, changes):
    before = config_path.read_text()
    result = store.update(changes)
    assert result.status == REJECTED_INVALID
    assert result.detail
    assert config_path.read_text() == before


def test_a_rejected_value_never_carries_pydantics_own_dump(store):
    result = store.update(
        {"drawer_arrangement": {"v": 1, "collapsed": ["bogus-fold-key"]}}
    )
    assert result.status == REJECTED_INVALID
    assert result.detail
    assert "\n" not in result.detail
    assert "validation error" not in result.detail.lower()
    assert "errors.pydantic.dev" not in result.detail
    assert "drawer_arrangement" in result.detail
    assert "bogus-fold-key" in result.detail


@pytest.mark.parametrize(
    "changes",
    [
        {"sidebar_density": "compact"},
        {"sidebar_density_mobile": "cozy"},
        {"widget_drawer_view": "type"},
        {"widget_drawer_view_mobile": "name"},
        {"sidebar_show_stats": False},
        {"sidebar_show_stats_mobile": True},
        {"sidebar_layout": "rail"},
        {"sidebar_layout": "classic"},
        {"sidebar_list_open": False},
        {"sidebar_list_sleeping_mobile": True},
        {"sidebar_show_closed": False},
        {"sidebar_show_closed_mobile": True},
        {"sidebar_hide_empty_sections": True},
        {"sidebar_hide_empty_sections": False},
        {"theme": "matrix"},
        {"launch_last_model": ""},
        {"launch_last_model": "anthropic/claude-sonnet-4"},
        {"sidebar_pinned": True},
        {"config_editor_collapsed": {"project:src": True}},
        {"launchpad_collapsed": {"recent-projects": True}},
        {"theme_favorites": ["matrix", "claude"]},
        {"theme_favorites": []},
        {"animations": False},
        {"animations": True},
        {"toast_mode": "compact"},
        {"toast_mode": "detailed"},
        {"terminal_screen_reader": "auto"},
        {"terminal_screen_reader": "on"},
        {"terminal_screen_reader": "off"},
        {"account_welcome_seen": True},
        {"foot_bar_items": {"agents": False}},
        {"foot_bar_items": {"model": False, "effort": False, "context": True}},
        {"foot_bar_items": {}},
    ],
)
def test_a_good_value_commits(store, changes):
    result = store.update(changes)
    assert result.status == COMMITTED, result.detail
    for name, value in changes.items():
        assert result.values[name] == value


@pytest.mark.parametrize(
    "changes, expect",
    [
        ({"foot_bar_layout": {"collapsed": "b"}}, {"collapsed": "b", "open": None}),
        ({"foot_bar_layout": {"collapsed": "b", "open": "c"}}, {"collapsed": "b", "open": "c"}),
        ({"foot_bar_layout": {}}, {"collapsed": None, "open": None}),
    ],
)
def test_foot_bar_layout_commits_with_the_unsent_half_absent(store, changes, expect):
    result = store.update(changes)
    assert result.status == COMMITTED, result.detail
    assert result.values["foot_bar_layout"] == expect


def test_a_stored_retired_header_quicklinks_is_hidden_and_dropped_on_the_next_write(store, config_path):
    doc = json.loads(config_path.read_text())
    doc[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": ui_preferences.SCHEMA_VERSION,
        "revision": 3,
        "values": {
            "theme": "matrix",
            "sidebar_density": "compact",
            "header_quicklinks": ["skills", "settings"],
        },
    }
    config_path.write_text(json.dumps(doc))
    store.invalidate()

    block = store.read()
    assert block["values"]["theme"] == "matrix"
    assert block["values"]["sidebar_density"] == "compact"
    assert "header_quicklinks" not in block["values"]

    result = store.update({"header_quicklinks": ["skills"], "theme": "claude"})
    assert result.status == COMMITTED, result.detail
    assert result.values["theme"] == "claude"
    assert result.values["sidebar_density"] == "compact"
    assert "header_quicklinks" not in result.values
    stored = json.loads(config_path.read_text())[ui_preferences.UI_PREFERENCES_KEY]["values"]
    assert "header_quicklinks" not in stored
    assert stored["sidebar_density"] == "compact"


def test_a_stored_retired_automations_show_huddle_still_loads_and_is_dropped(store, config_path):
    doc = json.loads(config_path.read_text())
    doc[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": ui_preferences.SCHEMA_VERSION,
        "revision": 2,
        "values": {"theme": "matrix", "automations_show_huddle": True},
    }
    config_path.write_text(json.dumps(doc))
    store.invalidate()

    block = store.read()
    assert block["values"]["theme"] == "matrix"
    assert "automations_show_huddle" not in block["values"]
    assert "automations_show_huddle" not in ui_preferences.known_fields()

    result = store.update({"automations_show_huddle": False, "theme": "claude"})
    assert result.status == COMMITTED, result.detail
    assert result.values["theme"] == "claude"
    stored = json.loads(config_path.read_text())[ui_preferences.UI_PREFERENCES_KEY]["values"]
    assert "automations_show_huddle" not in stored


def test_theme_favorites_drop_a_repeat_and_keep_first_order(store):
    result = store.update({"theme_favorites": ["matrix", "claude", "matrix"]})
    assert result.status == COMMITTED, result.detail
    assert result.values["theme_favorites"] == ["matrix", "claude"]


def test_an_emptied_favorites_list_is_kept_apart_from_never_set(store):
    store.update({"theme_favorites": ["matrix"]})
    emptied = store.update({"theme_favorites": []})
    assert emptied.values["theme_favorites"] == []
    unset = store.update({"theme_favorites": None})
    assert "theme_favorites" not in unset.values


RETIRED_TYPED_FIELDS = (
    "sidebar_arrangement", "config_editor_pinned", "warez_modem_sound", "install_report_notice_seen",
    "sidebar_show_open", "sidebar_show_open_mobile", "sidebar_show_sleeping", "sidebar_show_sleeping_mobile", "bell_kinds",
)


@pytest.mark.parametrize("field", RETIRED_TYPED_FIELDS)
def test_a_retired_typed_field_is_unknown_and_ignored_on_write(field):
    assert field in ui_preferences.RETIRED_FIELDS
    assert field not in ui_preferences.known_fields()
    typed = ui_preferences.validate_changes({field: "anything", "sidebar_density": "compact"})
    assert field not in typed and typed["sidebar_density"] == "compact"
    stored = {ui_preferences.UI_PREFERENCES_KEY: {"revision": 1, "values": {field: True, "sidebar_density": "cozy"}}}
    assert field not in ui_preferences.read_block(stored)["values"]


@pytest.mark.parametrize(
    "collapsed",
    [
        ["pinned", "other", "rogue"],
        ["terminals", "browsers"],
        ["files"],
        ["p:42", "g:abc"],
        ["layouts"],
        ["pack"],
        ["groups"],
        ["open", "sleeping"],
        ["ledger_hidden"],
        ["ledger_expanded"],
        ["ledger_glance"],
        ["layout:ef39fa3f-949f-4b90-9047-be7a45ed3737"],
    ],
)
def test_every_fold_key_shape_the_client_writes_is_accepted(store, collapsed):
    result = store.update(
        {"drawer_arrangement": {"v": 1, "collapsed": collapsed}}
    )
    assert result.status == COMMITTED, result.detail
    assert result.values["drawer_arrangement"]["collapsed"] == collapsed


def test_an_empty_change_set_is_refused(store):
    assert store.update({}).status == REJECTED_INVALID




def test_an_unrecognised_preference_in_the_block_survives_a_write(
    store, config_path
):
    data = _read(config_path)
    data[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": 1,
        "revision": 4,
        "values": {"a_field_from_a_newer_client": {"deep": [1, 2]}},
    }
    config_path.write_text(json.dumps(data, indent=2))
    store.invalidate()

    result = store.update({"theme": "matrix"})

    assert result.status == COMMITTED
    assert result.values["a_field_from_a_newer_client"] == {"deep": [1, 2]}
    assert result.values["theme"] == "matrix"
    assert result.revision == 5


def test_a_newer_clients_unknown_field_can_be_written_and_read_back(store):
    result = store.update({"a_field_from_a_newer_client": "hello"})
    assert result.status == COMMITTED
    assert store.read()["values"]["a_field_from_a_newer_client"] == "hello"


def test_an_oversized_unknown_value_is_refused(store):
    huge = "x" * (ui_preferences.MAX_UNKNOWN_VALUE_BYTES + 1)
    assert store.update({"future_field": huge}).status == REJECTED_INVALID


def test_the_revision_moves_only_when_something_actually_changed(store):
    first = store.update({"theme": "matrix"})
    assert first.status == COMMITTED
    assert first.revision == 1
    assert first.changed == {"theme": "matrix"}

    again = store.update({"theme": "matrix"})
    assert again.status == UNCHANGED
    assert again.revision == 1
    assert again.changed == {}


def test_none_unsets_a_field_and_counts_as_a_change(store):
    store.update({"theme": "matrix"})
    result = store.update({"theme": None})

    assert result.status == COMMITTED
    assert "theme" not in result.values
    assert result.changed == {"theme": None}
    assert result.revision == 2


def test_changed_names_only_the_fields_that_moved(store):
    store.update({"theme": "matrix", "sidebar_density": "compact"})
    result = store.update({"theme": "matrix", "sidebar_density": "cozy"})

    assert result.status == COMMITTED
    assert result.changed == {"sidebar_density": "cozy"}




def test_a_stale_revision_write_is_refused_and_says_what_is_current(store):
    store.update({"theme": "matrix"})
    store.update({"sidebar_density": "compact"})

    result = store.update({"theme": "claude"}, expected_revision=1)

    assert result.status == STALE_REVISION
    assert result.revision == 2
    assert result.values["theme"] == "matrix"
    assert result.values["sidebar_density"] == "compact"
    assert store.read()["values"]["theme"] == "matrix"


def test_without_the_revision_check_the_same_write_would_have_landed(store):
    store.update({"theme": "matrix"})
    store.update({"sidebar_density": "compact"})

    result = store.update({"theme": "claude"}, expected_revision=None)

    assert result.status == COMMITTED
    assert store.read()["values"]["theme"] == "claude"


def test_a_current_revision_is_accepted(store):
    store.update({"theme": "matrix"})
    result = store.update({"sidebar_density": "compact"}, expected_revision=1)
    assert result.status == COMMITTED
    assert result.revision == 2


def test_revision_zero_is_the_expected_revision_for_a_first_write(store):
    assert store.revision() == 0
    result = store.update({"theme": "matrix"}, expected_revision=0)
    assert result.status == COMMITTED


def test_two_concurrent_partial_updates_to_different_fields_both_survive(store):
    barrier = threading.Barrier(2)
    results: list = []

    def writer(changes):
        barrier.wait()
        time.sleep(0.02)
        results.append(store.update(changes))

    threads = [
        threading.Thread(target=writer, args=({"theme": "matrix"},)),
        threading.Thread(target=writer, args=({"sidebar_density": "compact"},)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    values = store.read()["values"]
    assert values["theme"] == "matrix"
    assert values["sidebar_density"] == "compact"
    assert store.revision() == 2
    assert all(result.status == COMMITTED for result in results)




def test_a_read_after_the_first_one_touches_no_file(store, monkeypatch):
    store.read()

    def refuse(*args, **kwargs):
        raise AssertionError("a preference read opened a file")

    monkeypatch.setattr(builtins, "open", refuse)
    assert store.read()["revision"] == 0
    assert store.revision() == 0


def test_a_write_by_any_other_config_writer_refreshes_the_projection(
    store, config_path
):
    store.read()

    config_writer.commit(
        config_path,
        lambda data: {
            **data,
            ui_preferences.UI_PREFERENCES_KEY: {
                "schema_version": 1,
                "revision": 9,
                "values": {"theme": "written-by-someone-else"},
            },
        },
    )

    assert store.read()["revision"] == 9
    assert store.read()["values"]["theme"] == "written-by-someone-else"


def test_a_caller_cannot_mutate_the_projection_through_the_dict_it_is_handed(store):
    store.update({"theme": "matrix"})
    block = store.read()
    block["values"]["theme"] = "tampered"
    assert store.read()["values"]["theme"] == "matrix"


def test_a_missing_config_reads_as_nothing_set_rather_than_raising(tmp_path: Path):
    store = UiPreferencesStore(lambda: tmp_path / "absent.json")
    block = store.read()
    assert block["revision"] == 0
    assert block["values"] == {}


def test_an_unparseable_config_reads_as_nothing_set_and_invents_no_default(
    tmp_path: Path,
):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    store = UiPreferencesStore(lambda: path)

    block = store.read()
    assert block["values"] == {}
    assert not any(field in block["values"] for field in ui_preferences.known_fields())


@pytest.mark.parametrize(
    "block",
    [
        {"revision": "seven", "values": {"theme": "matrix"}},
        {"revision": -1, "values": {"theme": "matrix"}},
        {"revision": True, "values": {}},
        {"values": "not an object"},
        "not an object at all",
        [],
    ],
)
def test_a_hand_edited_block_degrades_rather_than_raising(block):
    result = ui_preferences.read_block({ui_preferences.UI_PREFERENCES_KEY: block})
    assert isinstance(result["revision"], int)
    assert result["revision"] >= 0
    assert isinstance(result["values"], dict)


def test_wake_on_click_is_retired_and_a_stored_value_still_loads(store, config_path):
    assert "wake_on_click" in ui_preferences.RETIRED_FIELDS
    doc = json.loads(config_path.read_text())
    doc[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": ui_preferences.SCHEMA_VERSION, "revision": 2,
        "values": {"theme": "matrix", "wake_on_click": True},
    }
    config_path.write_text(json.dumps(doc))
    store.invalidate()
    assert "wake_on_click" not in store.read()["values"]
    result = store.update({"wake_on_click": False, "theme": "claude"})
    assert result.status == COMMITTED, result.detail
    assert "wake_on_click" not in json.loads(config_path.read_text())[ui_preferences.UI_PREFERENCES_KEY]["values"]


def test_show_colors_is_retired_and_a_stored_false_still_loads(store, config_path):
    for field in ("sidebar_show_colors", "sidebar_show_colors_mobile"):
        assert field in ui_preferences.RETIRED_FIELDS and field not in ui_preferences.known_fields()
    doc = json.loads(config_path.read_text())
    doc[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": ui_preferences.SCHEMA_VERSION, "revision": 2,
        "values": {"theme": "matrix", "sidebar_show_colors": False, "sidebar_show_colors_mobile": False},
    }
    config_path.write_text(json.dumps(doc))
    store.invalidate()
    assert "sidebar_show_colors" not in store.read()["values"]
    result = store.update({"sidebar_show_colors": True, "theme": "claude"})
    assert result.status == COMMITTED, result.detail
    stored = json.loads(config_path.read_text())[ui_preferences.UI_PREFERENCES_KEY]["values"]
    assert "sidebar_show_colors" not in stored and "sidebar_show_colors_mobile" not in stored


def test_animations_is_absent_until_set(store):
    assert "animations" in ui_preferences.known_fields()
    first = store.update({"theme": "matrix"})
    assert first.status == COMMITTED, first.detail
    assert first.values.get("animations") is None


def test_hide_empty_sections_is_absent_until_set_and_round_trips(store):
    assert "sidebar_hide_empty_sections" in ui_preferences.known_fields()
    first = store.update({"theme": "matrix"})
    assert first.status == COMMITTED, first.detail
    assert first.values.get("sidebar_hide_empty_sections") is None
    second = store.update({"sidebar_hide_empty_sections": True})
    assert second.status == COMMITTED, second.detail
    assert second.values["sidebar_hide_empty_sections"] is True


def test_menu_order_is_absent_until_dragged_and_round_trips(store):
    assert "menu_order" in ui_preferences.known_fields()
    first = store.update({"theme": "matrix"})
    assert first.status == COMMITTED, first.detail
    assert first.values.get("menu_order") is None
    second = store.update({"menu_order": ["settings", "projects", "settings"]})
    assert second.status == COMMITTED, second.detail
    assert second.values["menu_order"] == ["settings", "projects"]
    for bad in ([""], [1], ["x" * 200], [f"r{i}" for i in range(65)]):
        assert store.update({"menu_order": bad}).status != COMMITTED


def test_rail_hidden_icons_is_absent_until_chosen_and_round_trips(store):
    assert "rail_hidden_icons" in ui_preferences.known_fields()
    first = store.update({"theme": "matrix"})
    assert first.status == COMMITTED, first.detail
    assert first.values.get("rail_hidden_icons") is None
    second = store.update({"rail_hidden_icons": ["help", "core.swarm", "help"]})
    assert second.status == COMMITTED, second.detail
    assert second.values["rail_hidden_icons"] == ["help", "core.swarm"]
    for bad in ([""], [1], ["x" * 200], [f"r{i}" for i in range(65)]):
        assert store.update({"rail_hidden_icons": bad}).status != COMMITTED


def test_stored_crosstalk_card_switches_still_load_and_are_dropped_on_the_next_write(store, config_path):
    doc = json.loads(config_path.read_text())
    doc[ui_preferences.UI_PREFERENCES_KEY] = {
        "schema_version": ui_preferences.SCHEMA_VERSION,
        "revision": 2,
        "values": {"theme": "matrix", "crosstalk_cards_sent": False, "crosstalk_cards_received": True},
    }
    config_path.write_text(json.dumps(doc))
    store.invalidate()
    block = store.read()
    assert block["values"] == {"theme": "matrix"}
    result = store.update({"crosstalk_cards_sent": True, "theme": "claude"})
    assert result.status == COMMITTED, result.detail
    assert result.values["theme"] == "claude"
    stored = json.loads(config_path.read_text())[ui_preferences.UI_PREFERENCES_KEY]["values"]
    assert "crosstalk_cards_sent" not in stored and "crosstalk_cards_received" not in stored


def test_skill_favorites_take_real_names_and_refuse_control_characters(store):
    result = store.update({"skill_favorites": ["sme", "plugin:review", "sme"]})
    assert result.status == COMMITTED, result.detail
    assert result.values["skill_favorites"] == ["sme", "plugin:review"]
    real = store.update({"skill_favorites": ["Code Review", "r\u00e9sum\u00e9-\u30c4\u30fc\u30eb", "plugin:a b"]})
    assert real.status == COMMITTED, real.detail
    for bad in ("", "  ", "a\nb", "a\x00b", "x" * 201):
        assert store.update({"skill_favorites": [bad]}).status != COMMITTED


def test_elite_access_last_call_and_first_visit_round_trip_and_bad_values_are_refused(tmp_path, monkeypatch):
    for name, value in (("DEFAULT_WORKING_DIR", str(tmp_path)), ("LOG_DIRECTORY", str(tmp_path)), ("TOTP_SECRET", "testsecretnotreal"), ("JWT_SECRET", "testjwtnotreal")):
        monkeypatch.setenv(name, value)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.preferences_routes import router

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"agents": {"a": 1}}, indent=2))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.ui_preferences_store = UiPreferencesStore(lambda: config_path)
    with TestClient(app) as client:
        good = {"warez_last_call": "2026-10-18T12:30:05.123Z", "warez_elite_seen": True}
        assert client.patch("/api/v1/preferences", json={"changes": good}).status_code == 200
        held = client.get("/api/v1/preferences").json()
        assert {k: held["values"][k] for k in good} == good
        for bad in ({"warez_last_call": "yesterday"}, {"warez_last_call": "2026-10-18T12:30:05+02:00"}, {"warez_elite_seen": 1}, {"warez_elite_seen": "yes"}):
            response = client.patch("/api/v1/preferences", json={"changes": bad})
            assert response.status_code == 400, bad
            assert client.get("/api/v1/preferences").json() == held
