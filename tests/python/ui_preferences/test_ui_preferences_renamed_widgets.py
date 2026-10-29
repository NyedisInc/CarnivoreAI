
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
    assert set(RENAMED_WIDGETS.values()) <= ids and not set(RENAMED_WIDGETS) & ids
    assert {old: [new] for old, new in RENAMED_WIDGETS.items()} == {k: v for k, v in declared["replaced"].items() if k in RENAMED_WIDGETS}


def test_a_saved_rail_in_either_shape_reads_back_under_the_new_ids_and_keeps_every_other_key() -> None:
    flat = {"v": 1, "items": [{"widget": "core.files"}, {"widget": "core.huddle-list", "look": "full", "instance": "i2", "options": {"x": True}}]}
    split = {"v": 2, "sections": [{"items": [{"widget": "core.huddle"}]}, {"items": [{"widget": "core.huddle-all"}, {"widget": "core.notes"}]}], "ratio": 0.5}
    values = ui_preferences.read_block(_config({"session_rail": flat, "session_rail_bottom": split}))["values"]
    assert values["session_rail"]["items"] == [{"widget": "core.files"},
                                               {"widget": "core.task-list", "look": "full", "instance": "i2", "options": {"x": True}}]
    assert [i["widget"] for s in values["session_rail_bottom"]["sections"] for i in s["items"]] == [
        "core.task-manager", "core.task-manager-all", "core.notes"]
    assert values["session_rail_bottom"]["ratio"] == 0.5
    ui_preferences.validate_changes({"session_rail": values["session_rail"], "session_rail_bottom": values["session_rail_bottom"]})


def test_the_drawer_zone_items_and_glance_tiles_are_renamed_too() -> None:
    zone = {"v": 1, "items": [{"widget": "core.huddle-list"}], "glance": [{"id": "g-1", "widget": "core.huddle", "options": {}}]}
    out = ui_preferences.read_block(_config({"drawer_zone": zone}))["values"]["drawer_zone"]
    assert out["items"] == [{"widget": "core.task-list"}] and out["glance"] == [{"id": "g-1", "widget": "core.task-manager", "options": {}}]


def test_a_write_carrying_an_old_id_is_stored_under_the_new_one() -> None:
    changes = ui_preferences.validate_changes({"session_rail": {"v": 1, "items": [{"widget": "core.huddle-list"}]}})
    assert changes["session_rail"]["items"][0]["widget"] == "core.task-list"


def test_the_migration_is_idempotent_and_leaves_an_untouched_value_as_the_same_object() -> None:
    values = {"session_rail": {"v": 1, "items": [{"widget": "core.huddle-all"}]}, "drawer_zone": {"v": 1, "items": [{"widget": "core.notes"}]}}
    once = migrate_retired_placements(values)
    assert once["session_rail"]["items"][0]["widget"] == "core.task-manager-all"
    assert once["drawer_zone"] is values["drawer_zone"]
    assert migrate_retired_placements(once) is once
    assert values["session_rail"]["items"][0]["widget"] == "core.huddle-all"


def test_a_value_that_is_not_a_placement_passes_through() -> None:
    values = {"session_rail": None, "drawer_zone": "x", "theme": "carnivore"}
    assert migrate_retired_placements(values) is values
