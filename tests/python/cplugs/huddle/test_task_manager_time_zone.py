
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.core import ui_preferences
from src.core.time_zone import app_time_zone
from src.cplugs.huddle import recurrence
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, Env, call, env, iso  # noqa: F401

DAILY = {"freq": "daily", "time": "09:00"}
NEW_YORK, PARIS = ZoneInfo("America/New_York"), ZoneInfo("Europe/Paris")


@pytest.fixture()
def zone_pref():
    state: dict = {}
    app_time_zone.install(lambda: {"values": dict(state)})
    yield state
    app_time_zone.uninstall()


def wall(stamp: float, zone: ZoneInfo) -> tuple:
    moment = datetime.fromtimestamp(stamp, zone)
    return (moment.month, moment.day, moment.hour, moment.minute)


def test_daily_nine_is_computed_in_the_configured_zone_and_a_stored_instant_never_moves(client, env, zone_pref):
    after = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    assert wall(recurrence.next_after(DAILY, after), NEW_YORK) == (10, 5, 9, 0)

    item = env.add(client, text="stand-up notes")
    future = iso(3 * 24 * 3600)
    done = client.patch(f"{ITEMS}/{item['id']}", json={"repeat": DAILY, "fire_at": future})
    assert done.status_code == 200, done.text
    stored = env.trigger(item["id"])["fire_at"]

    zone_pref["time_zone"] = "Europe/Paris"
    assert app_time_zone.name() == "Europe/Paris"
    assert wall(recurrence.next_after(DAILY, after), PARIS)[2:] == (9, 0)
    assert wall(recurrence.next_after(DAILY, after), NEW_YORK)[2:] != (9, 0)
    assert env.trigger(item["id"])["fire_at"] == stored

    zone_pref["time_zone"] = None
    assert wall(recurrence.next_after(DAILY, after), NEW_YORK)[2:] == (9, 0)


def test_absent_or_unreadable_preference_reads_as_new_york(zone_pref):
    assert app_time_zone.name() == "America/New_York"
    zone_pref["time_zone"] = "Not/AZone"
    assert app_time_zone.name() == "America/New_York"


@pytest.mark.parametrize("bad", ["", "../etc/passwd", "Not/AZone", 5, "x" * 80])
def test_the_preference_refuses_a_bad_zone_name(bad):
    with pytest.raises(Exception):
        ui_preferences.validate_changes({"time_zone": bad})


def test_the_preference_accepts_an_iana_name_and_null():
    assert ui_preferences.validate_changes({"time_zone": "Asia/Tokyo"}) == {"time_zone": "Asia/Tokyo"}
    assert ui_preferences.validate_changes({"time_zone": None}) == {"time_zone": None}
