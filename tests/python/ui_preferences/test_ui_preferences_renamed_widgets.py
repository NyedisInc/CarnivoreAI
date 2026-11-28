
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import json
from pathlib import Path

from src.core import ui_preferences
from src.core.widget_placement.retired_widgets import RENAMED_WIDGETS, migrate_retired_placements

WIDGETS = Path(__file__).resolve().parents[3] / "src" / "data" / "widgets.json"


def _config(values):
    return {"ui_preferences": {"schema_version": 1, "revision": 4, "values": values}}


def test_every_renamed_widget_is_declared_and_every_old_id_is_listed_as_replaced_for_the_home_grid() -> None:
    declared = json.loads(WIDGETS.read_text())
    ids = {w["id"] for w in declared["widgets"]}
    assert set(RENAMED_WIDGETS.values()) == {"core.task-manager-mk2", "core.task-manager-mk2-all"} <= ids and not set(RENAMED_WIDGETS) & ids
    assert {old: [new] for old, new in RENAMED_WIDGETS.items()} == {k: v for k, v in declared["replaced"].items() if k in RENAMED_WIDGETS}


def test_a_saved_rail_in_either_shape_reads_back_under_the_new_ids_and_keeps_every_other_key() -> None:
    flat = {"v": 1, "items": [{"widget": "core.files"}, {"widget": "core.huddle-list", "look": "full", "instance": "i2", "options": {"x": True}}]}
    split = {"v": 2, "sections": [{"items": [{"widget": "core.huddle"}]}, {"items": [{"widget": "core.huddle-all"}, {"widget": "core.notes"}]}], "ratio": 0.5}
    values = ui_preferences.read_block(_config({"session_rail": flat, "session_rail_bottom": split}))["values"]
    assert values["session_rail"]["items"] == [{"widget": "core.files"},
                                               {"widget": "core.task-manager-mk2", "look": "full", "instance": "i2", "options": {"show_header": True}}]
    assert [i["widget"] for s in values["session_rail_bottom"]["sections"] for i in s["items"]] == [
        "core.task-manager-mk2", "core.task-manager-mk2-all", "core.notes"]
    assert values["session_rail_bottom"]["ratio"] == 0.5
    ui_preferences.validate_changes({"session_rail": values["session_rail"], "session_rail_bottom": values["session_rail_bottom"]})


def test_the_drawer_zone_items_and_glance_tiles_are_renamed_too() -> None:
    zone = {"v": 1, "items": [{"widget": "core.huddle-list"}], "glance": [{"id": "g-1", "widget": "core.huddle", "options": {}}]}
    out = ui_preferences.read_block(_config({"drawer_zone": zone}))["values"]["drawer_zone"]
    assert out["items"] == [{"widget": "core.task-manager-mk2", "options": {"show_header": True}}] and out["glance"] == [{"id": "g-1", "widget": "core.task-manager-mk2", "options": {}}]


def test_a_write_carrying_an_old_id_is_stored_under_the_new_one() -> None:
    changes = ui_preferences.validate_changes({"session_rail": {"v": 1, "items": [{"widget": "core.huddle-list"}]}})
    assert changes["session_rail"]["items"][0]["widget"] == "core.task-manager-mk2"


def test_the_migration_is_idempotent_and_leaves_an_untouched_value_as_the_same_object() -> None:
    values = {"session_rail": {"v": 1, "items": [{"widget": "core.huddle-all"}]}, "drawer_zone": {"v": 1, "items": [{"widget": "core.notes"}]}}
    once = migrate_retired_placements(values)
    assert once["session_rail"]["items"][0]["widget"] == "core.task-manager-mk2-all"
    assert once["drawer_zone"] is values["drawer_zone"]
    assert migrate_retired_placements(once) is once
    assert values["session_rail"]["items"][0]["widget"] == "core.huddle-all"


def test_a_value_that_is_not_a_placement_passes_through() -> None:
    values = {"session_rail": None, "drawer_zone": "x", "theme": "carnivore"}
    assert migrate_retired_placements(values) is values


def test_each_retired_widget_lands_on_its_mark_ii_equivalent() -> None:
    for old, new in (("core.task-manager", "core.task-manager-mk2"), ("core.task-list", "core.task-manager-mk2"),
                     ("core.task-manager-all", "core.task-manager-mk2-all")):
        out = migrate_retired_placements({"session_rail": {"v": 1, "items": [{"widget": old, "instance": "i2", "look": "full"}]}})
        header = {"options": {"show_header": True}} if old == "core.task-list" else {}
        assert out["session_rail"]["items"] == [{"widget": new, "instance": "i2", "look": "full", **header}]


def test_the_flat_list_drops_its_ticked_statuses_but_keeps_its_header_as_it_was_shown() -> None:
    hidden = {"widget": "core.task-list", "options": {"show_header": False, "status_open": True}}
    shown = {"widget": "core.task-list", "options": {"status_review": True}}
    side = migrate_retired_placements({"session_rail": {"v": 1, "items": [hidden]}})["session_rail"]["items"]
    bottom = migrate_retired_placements({"session_rail_bottom": {"v": 1, "items": [shown]}})["session_rail_bottom"]["items"]
    assert side == [{"widget": "core.task-manager-mk2", "options": {"show_header": False}}]
    assert bottom == [{"widget": "core.task-manager-mk2", "options": {"show_header": True}}]
    glance = migrate_retired_placements({"drawer_zone": {"v": 1, "glance": [shown]}})["drawer_zone"]["glance"]
    assert glance == [{"widget": "core.task-manager-mk2"}]


def test_any_ordinary_preference_write_stores_the_swapped_placement_once(tmp_path: Path) -> None:
    from src.core.ui_preferences_store import COMMITTED, UiPreferencesStore

    path = tmp_path / "config.json"
    rail = {"v": 1, "items": [{"widget": "core.task-list"}, {"widget": "core.notes"}]}
    path.write_text(json.dumps(_config({"session_rail": rail, "drawer_zone": {"v": 1, "items": [{"widget": "core.task-manager-all"}]}})))
    store = UiPreferencesStore(lambda: path)
    result = store.update({"sidebar_density": "compact"}, expected_revision=4)
    assert result.status == COMMITTED
    stored = json.loads(path.read_text())["ui_preferences"]["values"]
    assert [i["widget"] for i in stored["session_rail"]["items"]] == ["core.task-manager-mk2", "core.notes"]
    assert [i["widget"] for i in stored["drawer_zone"]["items"]] == ["core.task-manager-mk2-all"]
    assert "core.task-list" not in path.read_text() and "core.task-manager-all" not in path.read_text()


def test_a_rail_that_already_holds_mark_ii_keeps_it_and_loses_the_retired_duplicate() -> None:
    rail = {"v": 1, "items": [{"widget": "core.task-manager"}, {"widget": "core.notes"}, {"widget": "core.task-manager-mk2"}, {"widget": "core.task-list"}]}
    out = migrate_retired_placements({"session_rail": rail})["session_rail"]
    assert [i["widget"] for i in out["items"]] == ["core.notes", "core.task-manager-mk2"]
