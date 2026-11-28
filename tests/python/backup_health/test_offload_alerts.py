
from __future__ import annotations

from pathlib import Path

from src.core.backup_health import constants as K
from src.core.backup_health import vault_check, vault_record

NOW = 2_000_000_000.0


def record(state: Path, **alerts: dict) -> None:
    vault_record.update(state, active=True, last_ok_at=NOW, swept_at=NOW, uncovered=0, on_disk=0, offload_alerts=alerts)


def firing(state: Path) -> dict:
    return {v.key: v for v in vault_check.check_vault(state, NOW) if v.state == "firing"}


def test_a_purge_that_kept_files_is_one_sticky_error_naming_blobs_and_script(tmp_path) -> None:
    record(tmp_path, purge={"seq": 0, "conversations": ["c1"], "blobs": ["a" * 64], "at": NOW})
    verdict = firing(tmp_path)[K.KEY_VAULT_PURGE_UNVERIFIED]
    assert verdict.sticky and verdict.severity == "error"
    assert "a" * 64 in verdict.params["blobs"] and verdict.params["script"] == "scripts/vault/repair-chunks-from-restic.sh" and verdict.params["count"] == 1


def test_a_cleared_record_is_ok_and_a_new_finding_after_a_dismissal_gets_a_new_key(tmp_path) -> None:
    record(tmp_path, scrub={"seq": 0, "blobs": ["b" * 64], "at": NOW})
    assert K.KEY_VAULT_SCRUB_DAMAGED in firing(tmp_path)
    record(tmp_path, scrub={"seq": 0, "blobs": [], "at": NOW})
    assert not [k for k in firing(tmp_path) if k.startswith(K.KEY_VAULT_SCRUB_DAMAGED)]
    record(tmp_path, scrub={"seq": 1, "blobs": ["c" * 64], "at": NOW})
    assert f"{K.KEY_VAULT_SCRUB_DAMAGED}.1" in firing(tmp_path)


def test_no_record_means_every_offload_verdict_is_ok(tmp_path) -> None:
    assert all(v.state == "ok" for v in vault_check.check_vault(tmp_path, NOW))
