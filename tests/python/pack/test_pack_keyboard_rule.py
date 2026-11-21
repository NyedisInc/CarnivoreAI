
from datetime import datetime

from src.core.pack.machines.restrictions import Restrictions
from src.core.pack.reserve import model

NOON, NIGHT = datetime(2026, 10, 10, 12, 0), datetime(2026, 10, 10, 3, 0)


def test_rule_is_on_by_default():
    assert model.ReserveConfig().keyboard_rule.enabled is True
    assert model.from_dict(None).keyboard_rule.enabled is True


def test_readable_idle_decides_inside_and_outside_the_schedule():
    cfg = model.ReserveConfig()
    away = model.active(cfg, NOON, 11 * 60.0)
    assert (away["level"], away["source"]) == ("away", model.SOURCE_KEYBOARD)
    near = model.active(cfg, NIGHT, 60.0)
    assert (near["level"], near["source"]) == ("in_use", model.SOURCE_KEYBOARD)
    assert model.active(cfg, NOON, 9 * 60.0)["level"] == "in_use"


def test_unreadable_idle_falls_back_to_the_schedule_never_to_away():
    cfg = model.ReserveConfig()
    noon = model.active(cfg, NOON, None)
    assert (noon["level"], noon["source"]) == ("in_use", model.SOURCE_SCHEDULE)
    night = model.active(cfg, NIGHT, None)
    assert (night["level"], night["source"]) == ("away", model.SOURCE_SCHEDULE)


def test_rule_off_ignores_the_idle_time():
    off = model.merged(model.ReserveConfig(), {"keyboard_rule": {"enabled": False}})
    assert model.active(off, NOON, 99999.0)["level"] == "in_use"
    assert model.active(off, NIGHT, 1.0) == {"level": "away", "cpu_pct": 10, "mem_pct": 10, "source": model.SOURCE_SCHEDULE}


def test_stored_key_sets_are_pinned():
    dumped = model.ReserveConfig().model_dump()
    assert set(dumped) == {"in_use", "away", "schedule", "keyboard_rule"}
    assert set(dumped["in_use"]) == set(dumped["away"]) == {"cpu_pct", "mem_pct"}
    assert set(dumped["schedule"]) == {"in_use_from", "in_use_to", "days"}
    assert set(dumped["keyboard_rule"]) == {"enabled", "idle_minutes"}
    assert set(Restrictions().model_dump()) == {
        "allowed_companies", "allowed_projects", "max_agents", "may_host_agents", "may_install_tools", "may_receive_credentials",
        "may_receive_global_setup", "may_receive_projects", "may_update_carnivore"}
