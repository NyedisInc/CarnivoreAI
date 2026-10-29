
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.app_alerts import constants as AK
from src.core.app_alerts import service
from src.core.backup_health import checks, runner
from src.core.backup_health import constants as K
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated

NOW = 2_000_000_000.0
DAY = 86400.0


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    service.configure(db, None)
    drive = tmp_path / "Backup"
    drive.mkdir()
    monkeypatch.setattr(checks.os.path, "ismount", lambda p: Path(p) == drive)
    yield SimpleNamespace(state=state, db=db, drive=drive)
    service.configure(None, None)


def _run(w, now=NOW, volume=None):
    return runner.run_checks(w.state, w.db, now=now, volume=volume or w.drive)


def _active(w):
    rows = service.list_view(w.db, include_closed=False, limit=100)["alerts"]
    return {r["key"]: r for r in rows if r["state"] == AK.STATE_ACTIVE}


def _backup_dir(w, age_days):
    folder = w.drive / "state-backup-pre-1.12.20-20261001T000000Z"
    folder.mkdir(exist_ok=True)
    stamp = NOW - age_days * DAY
    os.utime(folder, (stamp, stamp))


def test_usb_backup_stale_missing_drive_and_resolve(world):
    _backup_dir(world, age_days=2)
    _run(world)
    assert K.KEY_USB not in _active(world)
    _backup_dir(world, age_days=K.BACKUP_MAX_AGE_DAYS + 3)
    _run(world)
    row = _active(world)[K.KEY_USB]
    assert row["title_key"] == K.TITLE_USB_STALE and row["severity"] == AK.SEV_WARN
    _backup_dir(world, age_days=1)
    assert _run(world)[K.KEY_USB] == "resolved" and K.KEY_USB not in _active(world)
    for child in world.drive.iterdir():
        child.rmdir()
    _run(world)
    assert _active(world)[K.KEY_USB]["title_key"] == K.TITLE_USB_STALE
    assert _run(world, volume=world.drive / "gone")[K.KEY_USB] == "raised"
    assert _active(world)[K.KEY_USB]["title_key"] == K.TITLE_USB_MISSING


def test_usb_check_can_be_switched_off_and_moved(monkeypatch):
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", "off")
    assert checks.backup_volume() is None and checks.check_usb_backup(NOW) is None
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", "/Volumes/Elsewhere")
    assert checks.backup_volume() == Path("/Volumes/Elsewhere")


def test_usb_check_is_off_unless_a_drive_is_named(world, monkeypatch):
    for name in ("CARNIVORE_BACKUP_VOLUME", "CLOUDE_BACKUP_VOLUME", "CLOUDECODE_BACKUP_VOLUME"):
        monkeypatch.delenv(name, raising=False)
    assert checks.backup_volume() is None and checks.check_usb_backup(NOW) is None
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", "")
    assert checks.backup_volume() is None
    outcome = runner.run_checks(world.state, world.db, now=NOW)
    assert K.KEY_USB not in outcome and K.KEY_USB not in _active(world)
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", str(world.drive / "gone"))
    assert runner.run_checks(world.state, world.db, now=NOW)[K.KEY_USB] == "raised"


def test_boot_seeding_retires_the_catchup_row_and_the_restore_point_alerts(world, tmp_path, monkeypatch):
    from src.core.automations import seed_backup, targets
    from src.core.automations.store import AutomationStore
    from src.core.automations.store_schema import storage_for

    monkeypatch.setitem(targets.RUNNERS, "recipe", lambda *a, **k: None)
    store = AutomationStore(storage_for(tmp_path / "auto"))
    target = {"kind": "recipe", "recipe": "backup_health_check", "params": {}}
    seeded = store.create(name="save catch-up", cron="0 * * * *", target=target, seed_key=K.RETIRED_CATCHUP_SEED_KEY)
    owned = store.create(name="mine", cron="5 * * * *", target=target)
    with closing(store._storage.connect(True)) as conn:
        conn.execute("UPDATE automations SET target = REPLACE(target, 'backup_health_check', 'save_catchup')")
        conn.commit()
    assert "backup_health.time_machine" in K.RETIRED_ALERT_KEYS
    for key in K.RETIRED_ALERT_KEYS + ("backup_health.time_machine",):
        service.raise_alert(key, source=K.ALERT_SOURCE, severity=AK.SEV_WARN, title_key="app_alert.x.title", db_path=world.db)
    assert set(K.RETIRED_ALERT_KEYS) | {"backup_health.time_machine"} <= set(_active(world))
    seed_backup.apply(store, world.db)
    seed_backup.apply(store, world.db)
    rows = store.list_all()
    assert [r["seed_key"] for r in rows] == [K.HEALTH_SEED_KEY]
    assert seeded["automation_id"] not in {r["automation_id"] for r in rows} and owned["automation_id"] not in {r["automation_id"] for r in rows}
    assert not (set(K.RETIRED_ALERT_KEYS) | {"backup_health.time_machine"}) & set(_active(world))
    _backup_dir(world, age_days=1)
    outcome = _run(world)
    assert outcome[K.KEY_USB] == "resolved"
    assert set(outcome) - {K.KEY_USB} == {
        K.KEY_VAULT_UNAVAILABLE, K.KEY_VAULT_STALE, K.KEY_VAULT_UNCOVERED, K.KEY_VAULT_OVER_CAP, K.KEY_VAULT_DAMAGED}


def test_usb_alert_from_a_named_drive_resolves_when_the_check_goes_off(world, monkeypatch):
    monkeypatch.setenv("CARNIVORE_BACKUP_VOLUME", str(world.drive / "gone"))
    assert runner.run_checks(world.state, world.db, now=NOW)[K.KEY_USB] == "raised"
    assert K.KEY_USB in _active(world)
    monkeypatch.delenv("CARNIVORE_BACKUP_VOLUME")
    assert K.KEY_USB not in runner.run_checks(world.state, world.db, now=NOW)
    assert K.KEY_USB not in _active(world)
