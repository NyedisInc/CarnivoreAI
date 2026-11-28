
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.backup_health import constants as K
from src.core.backup_health import runner, vault_record
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated

NOW = 2_000_000_000.0
GONE = {"count": 12, "samples": ["a", "b"], "at": NOW - 60, "step": 0}
FREEZE = {"count": 12, "samples": ["a"], "at": NOW - 60, "step": 0}


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    service.configure(db_path_for(state), None)
    yield SimpleNamespace(state=state, db=db_path_for(state), drive=tmp_path / "nodrive")
    service.configure(None, None)


def _record(world, **fields):
    base = dict(active=True, swept_at=NOW - 60, on_disk=40, uncovered=0, last_ok_at=NOW - 60, started_at=NOW - 9 * 3600,
                unavailable="", over_cap=False, damaged=0, pending=0)
    (world.state / vault_record.HEALTH_FILE).write_text(json.dumps({**base, **fields}), encoding="utf-8")


def _run(world):
    runner.run_checks(world.state, world.db, now=NOW, volume=world.drive)


def _mass_gone_action_ids(world):
    rows = service.list_view(world.db, include_closed=False, limit=100)["alerts"]
    row = next(r for r in rows if r["key"] == K.KEY_VAULT_MASS_GONE and r["state"] == AK.STATE_ACTIVE)
    return [a["id"] for a in row["actions"]]


def test_the_card_offers_clear_freeze_while_a_freeze_stands(world):
    _record(world, mass_gone=GONE, frozen=FREEZE)
    _run(world)
    assert "clear_freeze" in _mass_gone_action_ids(world)


def test_the_card_drops_clear_freeze_once_the_freeze_is_gone_and_keeps_dismiss_and_recheck(world):
    _record(world, mass_gone=GONE, frozen=FREEZE)
    _run(world)
    _record(world, mass_gone=GONE, frozen=None)
    _run(world)
    ids = _mass_gone_action_ids(world)
    assert "clear_freeze" not in ids and "recheck" in ids


def test_an_aged_out_sticky_card_drops_clear_freeze_when_no_freeze_remains(world):
    _record(world, mass_gone=GONE, frozen=FREEZE)
    _run(world)
    _record(world, mass_gone=None, frozen=None)
    _run(world)
    assert "clear_freeze" not in _mass_gone_action_ids(world)


def test_an_aged_out_sticky_card_keeps_clear_freeze_while_a_freeze_still_stands(world):
    _record(world, mass_gone=GONE, frozen=FREEZE)
    _run(world)
    _record(world, mass_gone=None, frozen=FREEZE)
    _run(world)
    assert "clear_freeze" in _mass_gone_action_ids(world)
