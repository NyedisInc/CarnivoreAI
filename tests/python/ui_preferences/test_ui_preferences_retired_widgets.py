
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.widget_placement.retired_widgets import approvals_only_options, migrate_retired_placements


def _config(values):
    return {"ui_preferences": {"schema_version": 1, "revision": 3, "values": values}}


def test_options_uncheck_all_huddle_and_automations_and_are_valid_option_keys():
    options = approvals_only_options()
    assert options == {"kind_all": False, "kind_huddle": False, "kind_automations": False}
    assert all(value is False for value in options.values())
    options["kind_all"] = True
    assert approvals_only_options()["kind_all"] is False


def test_a_saved_session_rail_in_either_shape_reads_back_as_an_approvals_only_questions_copy():
    flat = {"v": 1, "items": [{"widget": "core.files"}, {"widget": "core.approvals", "look": "full"}]}
    split = {"v": 2, "sections": [{"items": [{"widget": "core.notes"}]}, {"items": [{"widget": "core.approvals"}]}], "ratio": 0.5}
    values = ui_preferences.read_block(_config({"session_rail": flat, "session_rail_bottom": split}))["values"]
    moved = values["session_rail"]["items"][1]
    assert moved["widget"] == "core.questions" and moved["look"] == "full"
    assert moved["options"] == approvals_only_options()
    assert values["session_rail"]["items"][0] == {"widget": "core.files"}
    assert values["session_rail_bottom"]["sections"][1]["items"][0]["widget"] == "core.questions"
    ui_preferences.validate_changes({"session_rail": values["session_rail"], "session_rail_bottom": values["session_rail_bottom"]})


def test_drawer_zone_items_and_glance_tiles_migrate_and_a_taken_copy_id_is_skipped():
    zone = {
        "v": 1,
        "items": [{"widget": "core.questions"}, {"widget": "core.approvals"}, {"widget": "core.questions", "instance": "i2"}],
        "glance": [{"id": "g-1", "widget": "core.approvals", "options": {}}],
    }
    out = ui_preferences.read_block(_config({"drawer_zone": zone}))["values"]["drawer_zone"]
    assert [i["widget"] for i in out["items"]] == ["core.questions"] * 3
    assert out["items"][1]["instance"] == "i3"
    assert out["glance"][0] == {"id": "g-1", "widget": "core.questions", "options": {}}
    ui_preferences.validate_changes({"drawer_zone": out})


def test_a_write_of_a_stale_value_is_migrated_and_a_migrated_value_is_left_alone():
    stale = {"v": 1, "items": [{"widget": "core.approvals"}]}
    written = ui_preferences.validate_changes({"session_rail": stale})["session_rail"]
    assert written["items"][0]["widget"] == "core.questions"
    again = {"session_rail": written}
    assert migrate_retired_placements(again) is again


def test_values_without_a_retired_widget_come_back_as_the_same_object():
    values = {"session_rail": {"v": 1, "items": [{"widget": "core.files"}]}, "theme": "x"}
    assert migrate_retired_placements(values) is values
