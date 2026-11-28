
from __future__ import annotations

import inspect
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict

import pytest
from structlog.testing import capture_logs

from src.core import db
from src.core.db_migration import ensure_db_migrated
from src.core.boot import plugins as boot_plugins
from src.plugins.host import registry_store, renamed_entry, state as owner_state

PAIRS = {"huddle": "taskmanager"}
OLD = {"enabled": True, "grants": ["swarm", "notify"], "settings": {"nudgeMinutes": 30}, "revision": 4, "digest": "d1", "updated_at": 1.5}


@pytest.fixture(autouse=True)
def temp_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CARNIVORE_STATE_DIR", str(tmp_path))
    return tmp_path


def write_state(state_dir: Path, cplugs: Dict[str, Any]) -> None:
    path = registry_store.registry_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = registry_store.new_document()
    doc["items"] = {k: {"kind": "feature", **v} for k, v in cplugs.items()}
    path.write_text(json.dumps(doc), encoding="utf-8")


def read_cplugs(state_dir: Path) -> Dict[str, Any]:
    doc = json.loads(registry_store.registry_path(state_dir).read_text(encoding="utf-8"))
    out: Dict[str, Any] = {}
    for k, v in doc.get("items", {}).items():
        extracted = owner_state._extract_state_entry(v)
        if extracted is not None:
            out[k] = extracted
    return out


def add_ledger_row(state_dir: Path, plugin: str, install_id: str = "i1") -> None:
    ensure_db_migrated(state_dir)
    with closing(db.connect(db.db_path_for(state_dir))) as conn:
        conn.execute("INSERT INTO installed_items (install_id, item_id, kind, publisher, name, version, digest, scope, project_path, source_index_url,"
                     " publisher_key_id, installed_at, updated_at) VALUES (?, ?, 'cplug', 'nyedis', ?, '1.0.0', 'builtin:1', 'global', '', 'builtin',"
                     " 'builtin', 't', 't')", (install_id, f"nyedis/{plugin}", f"cplug-{plugin}"))


def ledger(state_dir: Path) -> list:
    with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
        return [tuple(r) for r in conn.execute("SELECT item_id, name FROM installed_items ORDER BY install_id")]


def test_the_entry_is_copied_whole_and_the_old_one_is_untouched(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD, "other": {"enabled": False}})
    before_old = read_cplugs(temp_state)["huddle"]
    out = renamed_entry.migrate(temp_state, PAIRS)
    cplugs = read_cplugs(temp_state)
    assert out.copied == ["huddle"] and not out.failed
    assert cplugs["taskmanager"] == OLD == before_old
    assert cplugs["huddle"] == before_old and cplugs["other"] == {"enabled": False}


def test_a_second_boot_changes_nothing(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    first = registry_store.registry_path(temp_state).read_bytes()
    out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.copied == [] and out.relabeled == 0
    assert registry_store.registry_path(temp_state).read_bytes() == first


def test_an_existing_new_entry_is_never_overwritten(temp_state: Path) -> None:
    mine = {"enabled": False, "grants": [], "settings": {}, "revision": 9}
    write_state(temp_state, {"huddle": OLD, "taskmanager": mine})
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []
    assert read_cplugs(temp_state)["taskmanager"] == mine


def test_no_old_entry_and_no_state_file_write_nothing(temp_state: Path) -> None:
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []
    assert not registry_store.registry_path(temp_state).exists()
    write_state(temp_state, {"other": {"enabled": True}})
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []
    assert "taskmanager" not in read_cplugs(temp_state)


def test_no_renames_is_a_no_op(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    assert renamed_entry.migrate(temp_state, {}) == renamed_entry.RenameOutcome()
    assert "taskmanager" not in read_cplugs(temp_state)


def test_the_manifests_drive_the_default_pairs(monkeypatch: pytest.MonkeyPatch, temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    monkeypatch.setattr(renamed_entry, "configured_renames", lambda: dict(PAIRS))
    assert renamed_entry.migrate(temp_state).copied == ["huddle"]


def test_a_corrupt_state_file_is_not_written_and_the_error_is_logged(temp_state: Path) -> None:
    path = registry_store.registry_path(temp_state)
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    with capture_logs() as logs:
        out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.failed and out.copied == []
    assert path.read_text(encoding="utf-8") == "{ not json"
    assert any(e["event"] == "cplug_renamed_entry_failed" and e["log_level"] == "error" for e in logs)


def test_the_ledger_rows_are_relabeled_in_one_transaction(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    add_ledger_row(temp_state, "huddle")
    add_ledger_row(temp_state, "other", "i2")
    out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.relabeled == 1
    assert ledger(temp_state) == [("nyedis/taskmanager", "cplug-taskmanager"), ("nyedis/other", "cplug-other")]
    assert renamed_entry.migrate(temp_state, PAIRS).relabeled == 0


def test_a_taken_new_label_skips_the_row_and_does_not_fail(temp_state: Path) -> None:
    add_ledger_row(temp_state, "huddle")
    add_ledger_row(temp_state, "taskmanager", "i2")
    out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.relabeled == 0 and not out.failed
    assert ledger(temp_state) == [("nyedis/huddle", "cplug-huddle"), ("nyedis/taskmanager", "cplug-taskmanager")]


def test_a_failed_ledger_update_rolls_back_every_row(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add_ledger_row(temp_state, "huddle")
    add_ledger_row(temp_state, "alpha", "i2")
    real = renamed_entry._relabel_one

    def boom(conn: sqlite3.Connection, old: str, new: str) -> int:
        real(conn, old, new)
        if old == "alpha":
            raise sqlite3.OperationalError("disk I/O error")
        return 1

    monkeypatch.setattr(renamed_entry, "_relabel_one", boom)
    out = renamed_entry.migrate(temp_state, {"huddle": "taskmanager", "alpha": "beta"})
    assert out.failed and out.relabeled == 0
    assert ledger(temp_state) == [("nyedis/huddle", "cplug-huddle"), ("nyedis/alpha", "cplug-alpha")]


def test_a_missing_database_is_skipped(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.relabeled == 0 and not out.failed and not db.db_path_for(temp_state).exists()


def test_revert_removes_an_unchanged_copy_only(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    assert renamed_entry.revert(temp_state, PAIRS).removed == ["huddle"]
    assert read_cplugs(temp_state) == {"huddle": OLD}
    assert renamed_entry.revert(temp_state, PAIRS).removed == []


def test_revert_keeps_a_copy_the_owner_changed(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    cplugs = read_cplugs(temp_state)
    cplugs["taskmanager"] = {**OLD, "settings": {"nudgeMinutes": 5}, "revision": 5}
    write_state(temp_state, cplugs)
    with capture_logs() as logs:
        assert renamed_entry.revert(temp_state, PAIRS).removed == []
    assert read_cplugs(temp_state)["taskmanager"]["settings"] == {"nudgeMinutes": 5}
    assert any(e["event"] == "cplug_renamed_entry_revert_kept" for e in logs)


def test_the_revert_command_uses_the_given_state_dir(temp_state: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    monkeypatch.setattr(renamed_entry, "app_answers", lambda port: False)
    assert renamed_entry.main(["--revert", "--state-dir", str(temp_state), "--pair", "huddle=taskmanager"]) == 0
    assert "taskmanager" not in read_cplugs(temp_state)
    assert "huddle" in capsys.readouterr().out


def test_the_boot_step_runs_before_the_split_swarm_default_and_fold_steps() -> None:
    source = inspect.getsource(boot_plugins._run_one_time_migrations)
    first = source.index("migrate_renamed_entries(")
    for later in ("migrate_split_plugins(", "migrate_swarm_default(", "migrate_folded_plugins("):
        assert first < source.index(later), later




def test_a_purged_new_entry_is_never_copied_back(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    assert renamed_entry.migrate(temp_state, PAIRS).copied == ["huddle"]
    assert owner_state.forget(temp_state, "taskmanager") is True
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []
    assert "taskmanager" not in read_cplugs(temp_state)


def test_the_carried_record_survives_a_later_state_write(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    assert owner_state.forget(temp_state, "huddle") is True
    owner_state.forget(temp_state, "taskmanager")
    write_state(temp_state, {"huddle": OLD})
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []


def test_an_unreadable_carried_record_copies_nothing(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    owner_state.forget(temp_state, "taskmanager")
    renamed_entry.carried_path(temp_state).write_text("{ not json", encoding="utf-8")
    out = renamed_entry.migrate(temp_state, PAIRS)
    assert out.failed and out.copied == [] and "taskmanager" not in read_cplugs(temp_state)


def test_a_new_entry_the_owner_already_answered_also_counts_as_carried(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD, "taskmanager": {"enabled": False}})
    renamed_entry.migrate(temp_state, PAIRS)
    owner_state.forget(temp_state, "taskmanager")
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []


def test_a_revert_that_removes_the_copy_lets_the_next_upgrade_copy_again(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    assert renamed_entry.revert(temp_state, PAIRS).removed == ["huddle"]
    assert renamed_entry.migrate(temp_state, PAIRS).copied == ["huddle"]


def test_a_failed_copy_is_not_recorded_so_the_next_boot_retries(temp_state: Path) -> None:
    path = registry_store.registry_path(temp_state)
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    assert renamed_entry.migrate(temp_state, PAIRS).failed
    assert not renamed_entry.carried_path(temp_state).exists()


def test_the_old_entry_is_forgotten_with_a_purge_of_the_new_id(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD, "taskmanager": OLD, "other": {"enabled": True}})
    assert renamed_entry.forget_old_entries(temp_state, "taskmanager", PAIRS) == ["huddle"]
    assert set(read_cplugs(temp_state)) == {"taskmanager", "other"}
    assert renamed_entry.forget_old_entries(temp_state, "other", PAIRS) == []


def test_revert_ignores_bookkeeping_that_a_boot_step_bumped(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    cplugs = read_cplugs(temp_state)
    cplugs["taskmanager"] = {**cplugs["taskmanager"], "revision": 9, "digest": "d2", "updated_at": 99.0}
    write_state(temp_state, cplugs)
    assert renamed_entry.revert(temp_state, PAIRS).removed == ["huddle"]


def test_revert_keeps_a_changed_grant(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    cplugs = read_cplugs(temp_state)
    cplugs["taskmanager"] = {**cplugs["taskmanager"], "grants": ["swarm"]}
    write_state(temp_state, cplugs)
    assert renamed_entry.revert(temp_state, PAIRS).removed == []


def test_revert_after_the_full_one_time_chain_still_removes_the_copy(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    write_state(temp_state, {"huddle": OLD})
    monkeypatch.setattr(renamed_entry, "configured_renames", lambda: dict(PAIRS))
    ctx = SimpleNamespace(datastore_state=SimpleNamespace(fresh_install=False))
    monkeypatch.setattr(boot_plugins.settings, "auth_config_file", str(temp_state / "config.json"))
    boot_plugins._run_one_time_migrations(ctx, temp_state)
    assert "taskmanager" in read_cplugs(temp_state)
    assert renamed_entry.revert(temp_state, PAIRS).removed == ["huddle"]


def test_a_skipped_ledger_row_is_logged_with_its_scope(temp_state: Path) -> None:
    add_ledger_row(temp_state, "huddle")
    add_ledger_row(temp_state, "taskmanager", "i2")
    with capture_logs() as logs:
        renamed_entry.migrate(temp_state, PAIRS)
    skipped = [e for e in logs if e["event"] == "cplug_renamed_ledger_skipped"]
    assert len(skipped) == 1 and skipped[0]["scope"] == "global" and skipped[0]["old"] == "huddle"


def test_the_ledger_names_come_from_the_one_shared_source() -> None:
    from src.core.skills import kinds
    from src.plugins.host import adoption, ledger_names

    assert renamed_entry.LEDGER_KIND is kinds.KIND_CPLUG
    assert renamed_entry.LEDGER_NAME_PREFIX is ledger_names.NAME_PREFIX is adoption.NAME_PREFIX




def test_revert_forgets_a_recorded_pair_whose_copy_a_restore_dropped(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    write_state(temp_state, {"huddle": OLD})
    assert renamed_entry.migrate(temp_state, PAIRS).copied == []
    out = renamed_entry.revert(temp_state, PAIRS)
    assert out.forgotten == ["huddle"] and out.removed == [] and not out.failed
    assert renamed_entry.migrate(temp_state, PAIRS).copied == ["huddle"]
    assert read_cplugs(temp_state)["taskmanager"] == OLD


def test_revert_keeps_a_recorded_pair_with_no_old_entry(temp_state: Path) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    write_state(temp_state, {})
    assert renamed_entry.revert(temp_state, PAIRS).forgotten == []
    assert json.loads(renamed_entry.carried_path(temp_state).read_text(encoding="utf-8"))["carried"] == PAIRS


def test_the_carried_record_is_an_accounted_store(temp_state: Path) -> None:
    from src.core.inventory import state_files

    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    assert renamed_entry.carried_path(temp_state).is_file()
    assert "cplugs/renamed-carried.json" not in state_files.unaccounted(temp_state)


def test_the_revert_command_refuses_while_the_app_answers(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_state(temp_state, {"huddle": OLD})
    renamed_entry.migrate(temp_state, PAIRS)
    monkeypatch.setattr(renamed_entry, "app_answers", lambda port: True)
    assert renamed_entry.main(["--revert", "--state-dir", str(temp_state), "--pair", "huddle=taskmanager", "--port", "1"]) == 1
    assert read_cplugs(temp_state)["taskmanager"] == OLD


def test_a_skipped_ledger_row_is_info_not_a_warning(temp_state: Path) -> None:
    add_ledger_row(temp_state, "huddle")
    add_ledger_row(temp_state, "taskmanager", "i2")
    with capture_logs() as logs:
        renamed_entry.migrate(temp_state, PAIRS)
    assert [e["log_level"] for e in logs if e["event"] == "cplug_renamed_ledger_skipped"] == ["info"]
