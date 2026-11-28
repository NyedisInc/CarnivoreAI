
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import List

import pytest
import structlog

from src.config import settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.backup_health import vault_moves
from src.core.claude_config import accounts_folder_cache
from src.core.provider_ledger import accounts_store, codex_homes, managed_profiles
from src.plugins.save import service
from src.plugins.save.vault import adopt, points, restore, retention, units
from src.plugins.save.vault import constants as K
from src.plugins.save.vault.identity import Identity
from src.plugins.save.vault.manifest import codex_account_home_key
from src.plugins.save.vault.units import CodexHome, Sources
from src.core.deepsearch.fallback_hook import FallbackPoint, IncomingFile
from src.plugins.sdk import transcript_files as tf, vault_sources
from tests.python.cplugs.save.vault_helpers import CODEX_ID, World, jsonl
from tests.test_provider_account_removal import MANAGED_CODEX, ACCOUNTS_URL, add, client  # noqa: F401

ACCOUNT_THREAD = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0002"
RELAY_THREAD = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0003"
MANAGED_THREAD = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0004"
ARCHIVED_THREAD = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0005"


def _rollout(home: Path, thread: str, sub: str = "sessions", lines: int = 5) -> Path:
    path = home / sub / "2026" / "03" / "01" / f"rollout-2026-03-01T10-00-00-{thread}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jsonl(lines))
    (path.parent / "auth.json").write_text(json.dumps({"tokens": {"access_token": "placeholder"}}))
    (path.parent / "state_5.sqlite").write_bytes(b"placeholder")
    return path


@pytest.fixture
def install(tmp_path, monkeypatch):
    accounts_root = tmp_path / "accounts"
    accounts_root.mkdir()
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(accounts_root))
    default = vault_sources.codex_home()
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    accounts_folder_cache.clear()
    account_home = accounts_root / "codex2"
    accounts_store.upsert_account(config, ProviderAccount(id="codex2", name="codex2", provider="codex", codex_home=str(account_home), managed=False))
    account_home.mkdir()
    return default, account_home, accounts_root / "0123456789ab-work-relay-codex"


def _sources(world: World, default: Path, *homes: Path) -> Sources:
    return Sources((), default, world.state, tuple(CodexHome(codex_account_home_key(h), h) for h in homes))


def _paths(plans) -> List[Path]:
    return [f.path for plan in plans.values() for f in plan.files]


def test_rollouts_of_every_account_codex_home_are_planned_and_only_rollouts(install):
    default, account_home, relay_home = install
    _rollout(default, CODEX_ID)
    _rollout(account_home, ACCOUNT_THREAD)
    _rollout(relay_home, RELAY_THREAD)
    plans = units.scan_codex(service.Runtime.sources())
    assert set(plans) == {CODEX_ID, ACCOUNT_THREAD, RELAY_THREAD}
    assert all(p.name.startswith("rollout-") and p.suffix == ".jsonl" for p in _paths(plans))


def test_a_managed_codex_account_home_is_planned(install, tmp_path, monkeypatch):
    default, _, _ = install
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = Path(settings.auth_config_file)
    accounts_store.upsert_account(config, ProviderAccount(id="mcodex", name="mcodex", provider="codex", managed=True))
    managed = Path(managed_dir_for("mcodex"))
    _rollout(managed, MANAGED_THREAD)
    assert set(units.scan_codex(service.Runtime.sources())) == {MANAGED_THREAD}


def test_archived_sessions_of_an_account_home_are_planned(install):
    _, account_home, _ = install
    _rollout(account_home, ARCHIVED_THREAD, sub="archived_sessions")
    plans = units.scan_codex(service.Runtime.sources())
    assert set(plans) == {ARCHIVED_THREAD}
    assert plans[ARCHIVED_THREAD].files[0].rel.startswith("archived_sessions/")


def test_the_same_thread_id_in_two_homes_stays_two_distinct_files(install, tmp_path):
    default, account_home, _ = install
    first = _rollout(default, CODEX_ID, lines=4)
    second = _rollout(account_home, CODEX_ID, lines=9)
    world = World(tmp_path / "w")
    plan = units.scan_codex(_sources(world, default, account_home))[CODEX_ID]
    keys = {(f.home, f.rel) for f in plan.files}
    assert len(plan.files) == 2 and len(keys) == 2, "two homes, same rel: the keys must differ"
    point = world.vault.capture(plan, Identity(), "follow")
    manifest = world.vault.manifests.read(CODEX_ID, point.point_id)
    assert {f.source_path for f in manifest.files} == {str(first), str(second)}
    assert sorted(f.length for f in manifest.files) == sorted([first.stat().st_size, second.stat().st_size])


def test_an_old_point_with_the_plain_codex_home_still_restores_to_the_default_home(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(default, CODEX_ID)
    world = World(tmp_path / "w")
    plan = units.scan_codex(_sources(world, default, account_home))[CODEX_ID]
    assert {f.home for f in plan.files} == {"codex"}
    point = world.vault.capture(plan, Identity(), "follow")
    body = src.read_bytes()
    src.unlink()
    out = points.restore_point(world.vault, CODEX_ID, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.transcript_path == src and src.read_bytes() == body


def test_a_rollout_restores_into_its_own_home(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    world = World(tmp_path / "w")
    plan = units.scan_codex(_sources(world, default, account_home))[ACCOUNT_THREAD]
    point = world.vault.capture(plan, Identity(), "follow")
    body = src.read_bytes()
    src.unlink()
    out = points.restore_point(world.vault, ACCOUNT_THREAD, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.status == restore.STATUS_WRITTEN and out.transcript_path == src and src.read_bytes() == body
    assert not list(default.rglob("rollout-*")), "nothing may land in the default home"


def test_a_rollout_already_on_disk_in_an_account_home_is_found_not_rewritten(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    world = World(tmp_path / "w")
    plan = units.scan_codex(_sources(world, default, account_home))[ACCOUNT_THREAD]
    point = world.vault.capture(plan, Identity(), "follow")
    out = points.restore_point(world.vault, ACCOUNT_THREAD, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.status == restore.STATUS_ALREADY_PRESENT and out.transcript_path == src


def test_removing_a_managed_codex_account_raises_no_mass_gone_alarm(client, tmp_path, monkeypatch):  # noqa: F811
    add(client, "codex1", MANAGED_CODEX)
    home = Path(managed_dir_for("codex1"))
    world = World(tmp_path / "w")
    for n in range(K.MASS_GONE_THRESHOLD + 2):
        _rollout(home, f"0199aaaa-bbbb-7ccc-8ddd-eeeeffff01{n:02d}")
    plans = units.scan_codex(Sources((), world.codex, world.state, (CodexHome(codex_account_home_key(home, "codex1"), home),)))
    assert len(plans) == K.MASS_GONE_THRESHOLD + 2
    for plan in plans.values():
        world.vault.capture(plan, Identity(), "follow")
    state = tf.state_dir()
    assert retention.assess(world.vault, moved_folders=vault_moves.recent_folders(state))["mass_gone"] is None
    order: List[str] = []
    real_remove = managed_profiles.remove_managed_dir

    def recording_remove(account_id):
        order.append("note-first" if str(home) in vault_moves.recent_folders(state) else "delete-first")
        return real_remove(account_id)

    monkeypatch.setattr(managed_profiles, "remove_managed_dir", recording_remove)
    assert client.delete(f"{ACCOUNTS_URL}/codex1").status_code == 200
    assert order == ["note-first"] and not home.exists()
    after = retention.assess(world.vault, now=time.time(), moved_folders=vault_moves.recent_folders(state))
    assert after["mass_gone"] is None
    assert set(world.vault.manifests.units()) == set(plans), "the vault keeps every copy"


def test_two_homes_sharing_a_folder_name_get_different_keys_and_both_files_are_kept(install, tmp_path):
    default, _, _ = install
    first, second = tmp_path / "a" / "codex2", tmp_path / "b" / "codex2"
    _rollout(first, CODEX_ID, lines=4)
    _rollout(second, CODEX_ID, lines=8)
    world = World(tmp_path / "w")
    assert codex_account_home_key(first) != codex_account_home_key(second)
    plan = units.scan_codex(_sources(world, default, first, second))[CODEX_ID]
    assert len({f.home for f in plan.files}) == 2
    manifest = world.vault.manifests.read(CODEX_ID, world.vault.capture(plan, Identity(), "follow").point_id)
    assert len(manifest.files) == 2


def test_a_managed_account_is_keyed_by_its_id_and_any_other_home_by_a_hash_of_its_real_path(tmp_path):
    home = tmp_path / "x"
    home.mkdir()
    assert codex_account_home_key(home, "codex1") == "codex@codex1"
    assert codex_account_home_key(home) == "codex@h-" + hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:12]
    assert codex_account_home_key(home, "bad id!") == codex_account_home_key(home)


def test_a_rollout_whose_account_is_gone_restores_into_the_default_home_and_says_so(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    world = World(tmp_path / "w")
    plan = units.scan_codex(_sources(world, default, account_home))[ACCOUNT_THREAD]
    point = world.vault.capture(plan, Identity(), "follow")
    body = src.read_bytes()
    accounts_store.remove_account(Path(settings.auth_config_file), "codex2")
    import shutil
    shutil.rmtree(account_home)
    out = points.restore_point(world.vault, ACCOUNT_THREAD, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.transcript_path == default / src.relative_to(account_home) and out.transcript_path.read_bytes() == body
    assert out.redirected_homes == (codex_account_home_key(account_home),)
    assert not account_home.exists(), "a removed account's folder is never recreated"


def test_a_point_written_with_the_old_basename_key_still_reads_and_restores(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    world = World(tmp_path / "w")
    plan = units.scan_codex(Sources((), default, world.state, (CodexHome("codex@codex2", account_home),)))[ACCOUNT_THREAD]
    point = world.vault.capture(plan, Identity(), "follow")
    assert world.vault.manifests.read(ACCOUNT_THREAD, point.point_id).files[0].home == "codex@codex2"
    body = src.read_bytes()
    src.unlink()
    out = points.restore_point(world.vault, ACCOUNT_THREAD, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.transcript_path.parent.parts[: len(default.parts)] == default.parts and out.transcript_path.read_bytes() == body


def _incoming(path: Path, rel: str, home: str, source_path: str, thread: str = ACCOUNT_THREAD) -> FallbackPoint:
    body = path.read_bytes()
    file = IncomingFile(role=K.ROLE_CODEX_ROLLOUT, home=home, rel=rel, source_path=source_path, length=len(body),
                        sha256=hashlib.sha256(body).hexdigest(), read=lambda: iter([body]))
    return FallbackPoint(conversation_id=thread, point_id="20261122T100000Z-import", reason="import", created_epoch=1.0, created_at="2026-11-22T10:00:00+00:00",
                         family="codex", files=(file,))


def test_a_crate_import_always_files_into_the_receiving_default_home(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    rel = str(src.relative_to(account_home))
    receiving = World(tmp_path / "receiving")
    for thread, key in ((ACCOUNT_THREAD, codex_account_home_key(account_home)), (CODEX_ID, "codex@sender-only-account")):
        done = adopt.adopt_points(receiving.vault, [_incoming(src, rel, key, "/sender/elsewhere/" + rel, thread=thread)], lambda entry: None)
        assert [d.status for d in done] == [adopt.ADOPTED]
        entry = receiving.vault.manifests.newest(thread).files[0]
        assert (entry.home, entry.source_path) == ("codex", str(default / rel))


def test_localize_itself_refuses_a_malformed_account_key(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    rel = str(src.relative_to(account_home))
    for key in ("codex@", "codex@a.b", "codex@../x", "codex@a/b", "codex@a b"):
        with pytest.raises(adopt.AdoptRefused):
            adopt.localize(_incoming(src, rel, key, "/x"), default)
    assert adopt.localize(_incoming(src, rel, "codex@h-0123456789ab", "/x"), default).files[0].home == "codex"


def test_a_redirected_restore_is_logged_at_info(install, tmp_path):
    default, account_home, _ = install
    _rollout(account_home, ACCOUNT_THREAD)
    world = World(tmp_path / "w")
    plan = units.scan_codex(Sources((), default, world.state, (CodexHome("codex@gone-account", account_home),)))[ACCOUNT_THREAD]
    point = world.vault.capture(plan, Identity(), "follow")
    with structlog.testing.capture_logs() as logs:
        out = points.restore_point(world.vault, ACCOUNT_THREAD, point.point_id, {"claude": tmp_path / "claude", "codex": default})
    assert out.redirected_homes == ("codex@gone-account",)
    assert [e["log_level"] for e in logs if e["event"] == "vault_restore_redirected"] == ["info"]


def test_a_hostile_crate_manifest_naming_a_path_outside_a_codex_sessions_folder_is_refused(install, tmp_path):
    default, account_home, _ = install
    src = _rollout(account_home, ACCOUNT_THREAD)
    receiving = World(tmp_path / "receiving")
    key = codex_account_home_key(account_home)
    for hostile in ("../../../escape.jsonl", "sessions/../../escape.jsonl", "auth.json", "projects/-x/escape.jsonl"):
        done = adopt.adopt_points(receiving.vault, [_incoming(src, hostile, key, "/etc/" + hostile)], lambda entry: None)
        assert [d.status for d in done] == [adopt.REFUSED], hostile
    assert receiving.vault.manifests.units() == []


def test_a_corrupt_config_is_a_warning_and_the_relay_folders_still_answer(install):
    _, _, relay_home = install
    relay_home.mkdir()
    Path(settings.auth_config_file).write_text("{not json")
    with structlog.testing.capture_logs() as logs:
        found = codex_homes.codex_account_homes(Path(settings.auth_config_file))
    assert [h.path for h in found] == [relay_home]
    assert [e["log_level"] for e in logs if e["event"] == "codex_homes_config_unreadable"] == ["warning"]
