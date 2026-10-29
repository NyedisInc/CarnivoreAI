
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from pydantic import ValidationError

from src.core import ui_preferences


def test_session_rail_is_a_known_field_and_absent_by_default():
    assert "session_rail" in ui_preferences.known_fields()
    assert ui_preferences.UiPreferenceValues().session_rail is None


def test_a_rail_round_trips_in_order_with_a_family_copy():
    values = ui_preferences.UiPreferenceValues(
        session_rail={"v": 1, "items": [
            {"widget": "core.task-manager"},
            {"widget": "core.changes"},
            {"widget": "core.terminal", "target": "row:7"},
        ]}
    )
    dumped = values.model_dump(exclude_none=True)["session_rail"]
    assert [i["widget"] for i in dumped["items"]] == ["core.task-manager", "core.changes", "core.terminal"]
    assert dumped["items"][2]["target"] == "row:7"


def test_an_emptied_rail_is_a_real_answer_distinct_from_absent():
    values = ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": []})
    assert values.model_dump(exclude_none=True)["session_rail"] == {"v": 1, "items": []}


@pytest.mark.parametrize(
    "bad",
    [
        {"v": 1, "items": [{"widget": "core.notes"}, {"widget": "core.notes"}]},
        {"v": 1, "items": [{"widget": f"core.w{i}"} for i in range(ui_preferences.MAX_SESSION_RAIL_ITEMS + 1)]},
        {"v": 1, "items": [{"widget": "Core Notes"}]},
        {"v": 1, "items": [{"widget": "core.notes", "look": "huge"}]},
        {"v": 1, "items": [], "glance": []},
        {"v": 1, "items": "core.notes"},
    ],
)
def test_a_bad_rail_is_refused(bad):
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(session_rail=bad)


def test_the_bottom_rail_is_a_known_field_absent_by_default_and_holds_more_than_twelve():
    assert "session_rail_bottom" in ui_preferences.known_fields()
    assert ui_preferences.UiPreferenceValues().session_rail_bottom is None
    many = {"v": 1, "items": [{"widget": f"core.w{i}"} for i in range(ui_preferences.MAX_DRAWER_ZONE_ITEMS + 8)]}
    values = ui_preferences.UiPreferenceValues(session_rail_bottom=many)
    assert len(values.model_dump(exclude_none=True)["session_rail_bottom"]["items"]) == ui_preferences.MAX_DRAWER_ZONE_ITEMS + 8


def test_the_bottom_rail_refuses_a_repeat():
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(session_rail_bottom={"v": 1, "items": [{"widget": "core.notes"}, {"widget": "core.notes"}]})




def test_a_split_rail_round_trips_with_its_ratio():
    values = ui_preferences.UiPreferenceValues(
        session_rail={"v": 2, "ratio": 0.4, "sections": [
            {"items": [{"widget": "core.changes"}]},
            {"items": [{"widget": "core.files"}, {"widget": "core.terminal", "target": "row:7"}]},
        ]}
    )
    dumped = values.model_dump(exclude_none=True)["session_rail"]
    assert dumped["v"] == 2
    assert dumped["ratio"] == 0.4
    assert [[i["widget"] for i in s["items"]] for s in dumped["sections"]] == [["core.changes"], ["core.files", "core.terminal"]]
    assert "items" not in dumped


def test_one_section_needs_no_ratio_and_may_be_empty():
    values = ui_preferences.UiPreferenceValues(session_rail_bottom={"v": 2, "sections": [{"items": []}]})
    assert values.model_dump(exclude_none=True)["session_rail_bottom"] == {"v": 2, "sections": [{"items": []}]}


def test_the_old_flat_value_still_reads():
    values = ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": [{"widget": "core.notes"}]})
    assert values.model_dump(exclude_none=True)["session_rail"] == {"v": 1, "items": [{"widget": "core.notes"}]}


@pytest.mark.parametrize(
    "bad",
    [
        {"v": 2, "ratio": 0.5, "sections": [{"items": [{"widget": "core.a"}]}, {"items": [{"widget": "core.b"}]}, {"items": [{"widget": "core.c"}]}]},
        {"v": 2, "ratio": 0.5, "sections": [{"items": [{"widget": "core.a"}]}, {"items": []}]},
        {"v": 2, "ratio": 0.5, "sections": [{"items": [{"widget": "core.a"}]}, {"items": [{"widget": "core.a"}]}]},
        {"v": 2, "ratio": 0.95, "sections": [{"items": [{"widget": "core.a"}]}, {"items": [{"widget": "core.b"}]}]},
        {"v": 2, "sections": [{"items": [{"widget": "core.a"}]}, {"items": [{"widget": "core.b"}]}]},
        {"v": 2, "ratio": 0.5, "sections": [{"items": [{"widget": "core.a"}]}]},
        {"v": 2, "items": [], "sections": [{"items": []}]},
        {"v": 2},
        {"v": 1, "items": [], "sections": [{"items": []}]},
        {"v": 3, "items": []},
        {"v": 2, "sections": []},
    ],
)
def test_a_bad_split_rail_is_refused(bad):
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(session_rail=bad)


def test_a_placement_stores_its_view_and_a_bad_view_is_refused():
    values = ui_preferences.UiPreferenceValues(
        session_rail={"v": 2, "sections": [{"items": [{"widget": "core.tasks", "view": "all"}, {"widget": "core.notes"}]}]}
    )
    items = values.model_dump(exclude_none=True)["session_rail"]["sections"][0]["items"]
    assert items[0]["view"] == "all"
    assert "view" not in items[1]
    for bad in ("All Sessions", "", "1all", "a" * 40):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": [{"widget": "core.tasks", "view": bad}]})


def test_a_widget_with_views_may_repeat_with_distinct_instance_keys():
    items = [{"widget": "core.tasks"}, {"widget": "core.tasks", "view": "all", "instance": "i2"}]
    values = ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": items})
    assert values.model_dump(exclude_none=True)["session_rail"]["items"][1]["instance"] == "i2"
    zone = ui_preferences.UiPreferenceValues(drawer_zone={"v": 1, "items": items})
    assert zone.model_dump(exclude_none=True)["drawer_zone"]["items"][1]["view"] == "all"


def test_the_same_copy_twice_and_a_bad_instance_are_refused():
    twice = [{"widget": "core.tasks", "instance": "i2"}, {"widget": "core.tasks", "instance": "i2"}]
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": twice})
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(drawer_zone={"v": 1, "items": twice})
    for bad in ("2", "I2", "i", "i1234", "copy"):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": [{"widget": "core.tasks", "instance": bad}]})


def test_each_copy_of_a_widget_keeps_its_own_options():
    items = [
        {"widget": "core.questions", "options": {"s_approvals": False}},
        {"widget": "core.questions", "instance": "i2", "options": {"s_huddle": False, "s_backup_health": False}},
    ]
    for field in ("session_rail", "drawer_zone"):
        dumped = ui_preferences.UiPreferenceValues(**{field: {"v": 1, "items": items}}).model_dump(exclude_none=True)[field]["items"]
        assert dumped[0]["options"] == {"s_approvals": False}
        assert dumped[1]["options"] == {"s_huddle": False, "s_backup_health": False}


def test_bad_placement_options_are_refused():
    many = {f"s_{n}": False for n in range(40)}
    for bad in (many, {"Bad Key": True}, {"s_a": "x" * 200}, {"s_a": 1.5}):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(session_rail={"v": 1, "items": [{"widget": "core.questions", "options": bad}]})
