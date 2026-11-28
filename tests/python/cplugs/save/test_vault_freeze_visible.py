
from __future__ import annotations

import json
from pathlib import Path

import src.config  # noqa: F401
from src.core.backup_health import constants as HK
from src.core.backup_health import vault_check, vault_record
from src.core.backup_health.checks import FIRING, OK
from src.plugins.save import location_check, settings_routes
from src.plugins.save.vault import constants as K
from src.plugins.save.vault import gone_watch, health, retention
from src.plugins.save.vault.follow import Engine
from src.plugins.sdk.blob_codec import Throttle
from tests.python.cplugs.save.test_vault_routes import BASE, rig  # noqa: F401
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

NOW = 2_000_000_000.0
FREEZE = '{"count": 10, "samples": ["/a"], "at": 1, "step": 0}'


def _freeze(world: World) -> None:
    (world.vault.root / K.FREEZE_FILE).write_text(FREEZE, encoding="utf-8")


def _grow(world: World, n: int) -> str:
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(3, seed=100 + n))
    return world.capture(reason="follow").status


def test_a_frozen_vault_under_its_cap_keeps_every_byte(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    _freeze(world)
    retention.write_state(world.vault.root, {"over_cap": False})
    assert [_grow(world, n) for n in range(3)] == ["written"] * 3
    main = next(f for f in world.vault.manifests.newest(CONV).files if f.role in K.MAIN_ROLES)
    assert main.length == world.transcript().stat().st_size


def test_the_engine_writes_the_freeze_into_the_health_record(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    _freeze(world)
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(sleep=lambda s: None), clock=lambda: NOW)
    engine.run_slice()
    frozen = health.read(world.state)["frozen"]
    assert frozen["count"] == 10 and frozen["at"] == 1


def test_get_health_and_backup_health_report_the_freeze(tmp_path, monkeypatch):
    record = {"active": True, "swept_at": NOW - 60, "on_disk": 5, "uncovered": 0, "last_ok_at": NOW - 60, "started_at": NOW - 3600,
              "over_cap": True, "frozen": {"count": 10, "at": 1, "step": 0}}
    (tmp_path / vault_record.HEALTH_FILE).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(settings_routes.tf, "state_dir", lambda: tmp_path)
    view = settings_routes.health_now()
    assert view.frozen is True and view.frozen_over_cap is True
    verdicts = {v.key: v for v in vault_check.check_vault(tmp_path, now=NOW)}
    frozen = verdicts[HK.KEY_VAULT_FROZEN]
    assert frozen.state == FIRING and frozen.detail_key == HK.DETAIL_VAULT_FROZEN_OVER_CAP
    (tmp_path / vault_record.HEALTH_FILE).write_text(json.dumps({**record, "over_cap": False}), encoding="utf-8")
    quiet = {v.key: v for v in vault_check.check_vault(tmp_path, now=NOW)}[HK.KEY_VAULT_FROZEN]
    assert quiet.state == FIRING and quiet.detail_key == HK.DETAIL_VAULT_FROZEN
    (tmp_path / vault_record.HEALTH_FILE).write_text(json.dumps({**record, "frozen": None}), encoding="utf-8")
    assert {v.key: v for v in vault_check.check_vault(tmp_path, now=NOW)}[HK.KEY_VAULT_FROZEN].state == OK


def test_a_vault_move_carries_the_freeze_to_the_new_folder(tmp_path, monkeypatch):
    state, old, new = tmp_path / "state", tmp_path / "old-vault", tmp_path / "new-vault"
    for folder in (state, old):
        folder.mkdir()
    (old / K.FREEZE_FILE).write_text(FREEZE, encoding="utf-8")
    monkeypatch.setattr(location_check.tf, "state_dir", lambda: state)
    monkeypatch.setattr(location_check.location, "resolve_root", lambda _state: old)
    monkeypatch.setattr(location_check.location, "ensure_root", lambda root: Path(root).mkdir(exist_ok=True))
    monkeypatch.setattr(location_check, "warnings_for", lambda root: [])
    verdict = location_check.check_settings({"vaultLocation": str(new)})
    assert gone_watch.frozen(new) is None
    carried = verdict.after_store()
    assert gone_watch.frozen(new)["count"] == 10 and (old / K.FREEZE_FILE).is_file()
    assert any(w.code == location_check.FREEZE_CARRIED_CODE for w in carried)


def test_a_vault_move_with_no_freeze_carries_nothing(tmp_path, monkeypatch):
    state, old, new = tmp_path / "state", tmp_path / "old-vault", tmp_path / "new-vault"
    for folder in (state, old):
        folder.mkdir()
    monkeypatch.setattr(location_check.tf, "state_dir", lambda: state)
    monkeypatch.setattr(location_check.location, "resolve_root", lambda _state: old)
    monkeypatch.setattr(location_check.location, "ensure_root", lambda root: Path(root).mkdir(exist_ok=True))
    monkeypatch.setattr(location_check, "warnings_for", lambda root: [])
    verdict = location_check.check_settings({"vaultLocation": str(new)})
    if verdict.after_store is not None:
        assert verdict.after_store() == []
    assert gone_watch.frozen(new) is None


def test_a_refused_or_stale_save_carries_no_freeze_and_a_stored_one_does(rig):
    client, state, _corpus, tmp = rig
    (state / "vault").mkdir(exist_ok=True)
    (state / "vault" / K.FREEZE_FILE).write_text(FREEZE, encoding="utf-8")
    chosen = tmp / "chosen"
    chosen.mkdir()
    revision = client.get(BASE).json()["revision"]
    stale = client.put(BASE, json={"revision": revision + 99, "settings": {"vaultLocation": str(chosen / "vault")}})
    assert stale.status_code == 409
    assert not (chosen / "vault" / K.FREEZE_FILE).exists()
    stored = client.put(BASE, json={"revision": revision, "settings": {"vaultLocation": str(chosen / "vault")}})
    assert stored.status_code == 200
    assert gone_watch.frozen(chosen / "vault")["count"] == 10
    assert any(w["code"] == location_check.FREEZE_CARRIED_CODE for w in stored.json()["settings_warnings"])
