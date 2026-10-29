
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dz_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dz_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from pydantic import ValidationError

from src.core import ui_preferences


def test_drawer_zone_is_a_known_field_and_absent_by_default():
    assert "drawer_zone" in ui_preferences.known_fields()
    assert ui_preferences.UiPreferenceValues().drawer_zone is None


def test_a_zone_with_looks_round_trips():
    values = ui_preferences.UiPreferenceValues(
        drawer_zone={"v": 1, "items": [{"widget": "core.ledger", "look": "full"}, {"widget": "core.keep-awake"}]}
    )
    dumped = values.model_dump(exclude_none=True)["drawer_zone"]
    assert [i["widget"] for i in dumped["items"]] == ["core.ledger", "core.keep-awake"]
    assert dumped["items"][0]["look"] == "full"


def test_family_copies_with_different_targets_share_the_zone():
    values = ui_preferences.UiPreferenceValues(
        drawer_zone={"items": [{"widget": "core.terminal", "target": "row:7"}, {"widget": "core.terminal", "target": "row:8"},
                               {"widget": "core.analytics", "target": "c-abc"}]}
    )
    dumped = values.model_dump(exclude_none=True)["drawer_zone"]
    assert [(i["widget"], i["target"]) for i in dumped["items"]] == [
        ("core.terminal", "row:7"), ("core.terminal", "row:8"), ("core.analytics", "c-abc")]


def test_an_emptied_zone_is_a_real_answer_distinct_from_absent():
    values = ui_preferences.UiPreferenceValues(drawer_zone={"items": []})
    assert values.drawer_zone is not None and values.drawer_zone.items == []


@pytest.mark.parametrize(
    "bad",
    [
        {"items": [{"widget": "core.ledger"}, {"widget": "core.ledger"}]},
        {"items": [{"widget": "core.ledger", "look": "huge"}]},
        {"items": [{"widget": "Core Ledger"}]},
        {"items": [{"widget": f"w{i}"} for i in range(ui_preferences.MAX_DRAWER_ZONE_ITEMS + 1)]},
        {"items": [{"widget": "core.ledger", "extra": 1}]},
        {"items": [{"widget": "core.terminal", "target": "row:7"}, {"widget": "core.terminal", "target": "row:7"}]},
        {"items": [{"widget": "core.terminal", "target": "row 7; rm"}]},
    ],
)
def test_a_bad_zone_is_refused(bad):
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(drawer_zone=bad)


def test_the_glance_area_is_absent_until_written_and_takes_repeats_with_their_own_options():
    absent = ui_preferences.UiPreferenceValues(drawer_zone={"items": []})
    assert absent.drawer_zone.glance is None
    values = ui_preferences.UiPreferenceValues(
        drawer_zone={
            "items": [{"widget": "core.ledger"}],
            "glance": [
                {"id": "g-a", "widget": "core.ledger", "options": {"account": "acc_one"}},
                {"id": "g-b", "widget": "core.ledger", "options": {"account": "acc_two"}},
            ],
        }
    )
    dumped = values.model_dump(mode="json")["drawer_zone"]["glance"]
    assert [(p["id"], p["options"]["account"]) for p in dumped] == [("g-a", "acc_one"), ("g-b", "acc_two")]


@pytest.mark.parametrize(
    "bad",
    [
        [{"id": "g-a", "widget": "core.ledger"}, {"id": "g-a", "widget": "core.ledger"}],
        [{"id": "G A", "widget": "core.ledger"}],
        [{"id": "g-a", "widget": "core.ledger", "options": {"Account": "x"}}],
        [{"id": "g-a", "widget": "core.ledger", "options": {"account": "x" * 200}}],
        [{"id": "g-a", "widget": "core.ledger", "options": {"account": {"nested": 1}}}],
        [{"id": f"g-{i}", "widget": "core.ledger"} for i in range(13)],
    ],
)
def test_a_bad_glance_area_is_refused(bad):
    with pytest.raises(ValidationError):
        ui_preferences.UiPreferenceValues(drawer_zone={"items": [], "glance": bad})
