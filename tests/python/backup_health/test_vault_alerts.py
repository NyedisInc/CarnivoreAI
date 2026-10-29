
from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.backup_health import constants as K
from src.core.backup_health import runner, vault_check, vault_record
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated

NOW = 2_000_000_000.0
HOUR = 3600.0


@pytest.fixture()
def world(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    service.configure(db, None)
    yield SimpleNamespace(state=state, db=db, drive=tmp_path / "nodrive")
    service.configure(None, None)


def _record(world, **fields):
    base = dict(active=True, swept_at=NOW - 60, on_disk=40, uncovered=0, last_ok_at=NOW - 60, started_at=NOW - 9 * HOUR,
                unavailable="", over_cap=False, damaged=0, pending=0)
    (world.state / vault_record.HEALTH_FILE).write_text(__import__("json").dumps({**base, **fields}), encoding="utf-8")


def _run(world):
    return runner.run_checks(world.state, world.db, now=NOW, volume=world.drive)


def _active(world):
    rows = service.list_view(world.db, include_closed=False, limit=100)["alerts"]
    return {r["key"]: r for r in rows if r["state"] == AK.STATE_ACTIVE and r["key"].startswith("backup_health.vault")}


def test_uncovered_conversations_alert_only_after_the_grace_and_resolve(world):
    _record(world, uncovered=7, uncovered_since=NOW - 30 * 60)
    _run(world)
    assert K.KEY_VAULT_UNCOVERED not in _active(world)
    _record(world, uncovered=7, uncovered_since=NOW - 3 * HOUR)
    _run(world)
    row = _active(world)[K.KEY_VAULT_UNCOVERED]
    assert row["title_key"] == K.TITLE_VAULT_UNCOVERED and row["params"] == {"count": 7, "on_disk": 40}
    _record(world, uncovered=0, uncovered_since=None)
    assert _run(world)[K.KEY_VAULT_UNCOVERED] == "resolved" and K.KEY_VAULT_UNCOVERED not in _active(world)


def test_a_stale_vault_alerts_with_the_hours_and_resolves_on_the_next_pass(world):
    _record(world, last_ok_at=NOW - 9 * HOUR)
    _run(world)
    row = _active(world)[K.KEY_VAULT_STALE]
    assert row["params"] == {"hours": 9, "max_hours": 6}
    _record(world, last_ok_at=NOW - 60)
    assert _run(world)[K.KEY_VAULT_STALE] == "resolved"


def test_an_unavailable_location_alerts_once_and_does_not_also_read_as_stale(world):
    _record(world, unavailable="the volume /Volumes/Vault is not mounted", last_ok_at=NOW - 20 * HOUR)
    _run(world)
    active = _active(world)
    assert active[K.KEY_VAULT_UNAVAILABLE]["severity"] == AK.SEV_ERROR
    assert "mounted" in active[K.KEY_VAULT_UNAVAILABLE]["params"]["reason"]
    assert K.KEY_VAULT_STALE not in active and K.KEY_VAULT_UNCOVERED not in active


def test_over_cap_and_damaged_chunks_alert(world):
    _record(world, over_cap=True, damaged=3)
    _run(world)
    active = _active(world)
    assert K.KEY_VAULT_OVER_CAP in active and active[K.KEY_VAULT_DAMAGED]["params"] == {"count": 3}


def test_no_record_or_a_plugin_that_is_off_never_alerts_and_clears_an_open_alert(world):
    assert all(v.state == "ok" for v in vault_check.check_vault(world.state, NOW))
    _record(world, last_ok_at=NOW - 9 * HOUR, over_cap=True)
    _run(world)
    assert _active(world)
    _record(world, last_ok_at=NOW - 9 * HOUR, over_cap=True, active=False)
    _run(world)
    assert not _active(world)


def test_an_unmeasured_coverage_is_unknown_not_zero(world):
    _record(world, swept_at=None, uncovered=None)
    verdicts = {v.key: v.state for v in vault_check.check_vault(world.state, NOW)}
    assert verdicts[K.KEY_VAULT_UNCOVERED] == "unknown"
