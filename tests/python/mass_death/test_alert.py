
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.app_alerts import service
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mass_death import detector, notice


@pytest.fixture()
def world(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    frames: list = []
    service.configure(db, frames.append)
    fresh = detector.MassDeathDetector()
    previous = detector.DETECTOR
    detector.DETECTOR = fresh
    yield SimpleNamespace(db=db, frames=frames, det=fresh)
    detector.DETECTOR = previous
    service.configure(None, None)


def _active(world) -> list:
    return [a for a in service.list_view(world.db, include_closed=False, limit=50)["alerts"] if a["key"] == notice.ALERT_KEY]


def test_one_dead_pane_raises_no_alert(world):
    assert detector.observe(["a"], now=0.0) is None
    assert _active(world) == []


def test_three_dead_panes_raise_one_alert_with_the_resume_action(world):
    event = detector.observe(["a", "b", "c"], now=0.0)
    assert event is not None
    (alert,) = _active(world)
    assert alert["params"]["count"] == "3"
    action = alert["actions"][0]
    assert (action["method"], action["route"]) == ("POST", notice.RESUME_ROUTE)
    assert action["body"] == {"session_uuids": ["a", "b", "c"]}
    assert action["label_key"] == "app_alert.action.mass_death_resume"


def test_a_growing_burst_updates_the_same_alert_and_toasts_once(world):
    detector.observe(["a", "b", "c"], now=0.0)
    detector.observe(["d"], now=2.0)
    (alert,) = _active(world)
    assert alert["params"]["count"] == "4" and len(alert["actions"][0]["body"]["session_uuids"]) == 4
    raised = [f for f in world.frames if f.get("event", f.get("type")) == "app_alert.raised"]
    assert len(raised) == 1


def test_resolve_closes_the_alert(world):
    detector.observe(["a", "b", "c"], now=0.0)
    notice.resolve()
    assert _active(world) == []
