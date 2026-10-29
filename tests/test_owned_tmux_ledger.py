
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger


class _NoDatastore:

    def read_connection(self) -> None:
        return None

    def write_connection(self) -> None:
        return None

    def get_instance(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> None:
        return None


def _ledger(tmp_path: Path) -> OwnedTmuxLedger:
    target = tmp_path / "state" / "session_metadata.json"
    return OwnedTmuxLedger(
        metadata_path=lambda: target,
        records=_NoDatastore(),
        socket_name=lambda: "cloude-test",
    )




def test_the_manager_and_the_ledger_are_the_same_object():
    manager = SessionManager()
    assert isinstance(manager._owned, OwnedTmuxLedger)
    assert manager._owned.names is manager._owned.names


def test_a_name_added_through_the_manager_is_visible_on_the_ledger():
    manager = SessionManager()
    ledger = manager._owned

    manager._owned.names.add("cloude_forward")

    assert "cloude_forward" in ledger.names


def test_a_name_added_on_the_ledger_is_visible_through_the_manager():
    manager = SessionManager()
    ledger = manager._owned

    ledger.names.add("cloude_reverse")

    assert "cloude_reverse" in manager._owned.names


def test_the_set_survives_a_round_trip_through_the_file_as_one_object(tmp_path):
    first = _ledger(tmp_path)
    first.names.update({"cloude_a", "cloude_b"})
    assert first.save({"id": "ses_1", "working_dir": "/tmp/x"}) is True

    second = _ledger(tmp_path)
    load = second.load()

    assert second.names == {"cloude_a", "cloude_b"}
    assert load.session is not None and load.session["id"] == "ses_1"
    assert "owned_tmux_sessions" not in load.session, (
        "the v3 field leaked into the Session payload; Session(**raw) is "
        "what receives this and it does not know that name"
    )

    first.names.add("cloude_c")
    assert "cloude_c" not in second.names, (
        "two ledgers over one file share an in-memory set; they must not"
    )




def test_the_write_goes_through_a_temp_file_and_a_rename(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    seen: list[tuple[str, str, bool]] = []
    real_replace = os.replace

    def _spy(src, dst):
        seen.append((str(src), str(dst), Path(src).exists()))
        return real_replace(src, dst)

    monkeypatch.setattr(
        "src.core.safe_io.atomic_write.os.replace", _spy
    )
    ledger.write_atomic({"owned_tmux_sessions": ["cloude_a"]})

    assert len(seen) == 1, "the write did not go through os.replace"
    src, dst, existed = seen[0]
    assert dst == str(ledger.path())
    assert src != dst, "renamed the destination onto itself"
    assert src.endswith(".tmp")
    assert existed, "os.replace was called but nothing had been written to src"
    assert json.loads(ledger.path().read_text()) == {
        "owned_tmux_sessions": ["cloude_a"]
    }
    assert not Path(src).exists(), "the temp file was left behind"


def test_the_write_creates_its_parent_directory(tmp_path):
    ledger = _ledger(tmp_path)
    assert not ledger.path().parent.exists()

    ledger.write_atomic({"owned_tmux_sessions": []})

    assert ledger.path().exists()




def test_dropping_the_pointer_keeps_the_owned_set(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.names.update({"cloude_alpha", "cloude_beta"})
    ledger.save({"id": "ses_dead", "working_dir": "/tmp/x"})

    ledger.drop_session_pointer()

    reborn = _ledger(tmp_path)
    load = reborn.load()
    assert load.session is None, "the dead pointer was kept"
    assert reborn.names == {"cloude_alpha", "cloude_beta"}, (
        "the owned set went with the pointer"
    )


def test_dropping_the_pointer_with_no_owned_names_leaves_no_file(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.save({"id": "ses_dead", "working_dir": "/tmp/x"})
    assert ledger.path().exists()

    ledger.drop_session_pointer()

    assert not ledger.path().exists()




def test_an_absent_file_leaves_the_ledger_exactly_as_it_was(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.names.add("cloude_held")

    load = ledger.load()

    assert load.session is None
    assert ledger.names == {"cloude_held"}


def test_an_unreadable_file_leaves_the_ledger_exactly_as_it_was(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.names.add("cloude_held")
    ledger.path().parent.mkdir(parents=True, exist_ok=True)
    ledger.path().write_text("{not json at all")

    load = ledger.load()

    assert load.session is None
    assert ledger.names == {"cloude_held"}


def test_an_owned_set_only_payload_loads_the_set_and_no_session(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.path().parent.mkdir(parents=True, exist_ok=True)
    ledger.path().write_text(json.dumps({"owned_tmux_sessions": ["cloude_x"]}))

    load = ledger.load()

    assert load.session is None
    assert ledger.names == {"cloude_x"}
    assert ledger.needs_legacy_backfill is False


def test_a_pre_v3_payload_arms_the_backfill_sentinel(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.path().parent.mkdir(parents=True, exist_ok=True)
    ledger.path().write_text(json.dumps({"id": "ses_old", "working_dir": "/tmp/x"}))

    load = ledger.load()

    assert load.session is not None
    assert ledger.names == set()
    assert ledger.needs_legacy_backfill is True


def test_a_successful_save_is_the_migration(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.needs_legacy_backfill = True

    ledger.save({"id": "ses_old", "working_dir": "/tmp/x"})

    assert ledger.needs_legacy_backfill is False




def test_a_datastore_with_no_opinion_is_not_a_report_of_owning_nothing(tmp_path):
    ledger = _ledger(tmp_path)

    assert ledger.instances_from_db() is None
    assert ledger.instances() is None


def test_the_name_tier_answers_from_the_set_when_the_datastore_is_silent(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.names.add("cloude_ours")

    assert ledger.is_owned_name("cloude_ours") is True
    assert ledger.is_owned_name("cloude_theirs") is False
    assert ledger.is_owned_name("") is False
    assert ledger.is_owned_name(None) is False


@pytest.mark.parametrize("name", ["cloude_lookalike", "cloude_", "cloude_ours_2"])
def test_a_name_that_merely_looks_like_ours_is_not_owned(tmp_path, name: str):
    ledger = _ledger(tmp_path)
    ledger.names.add("cloude_ours")

    assert ledger.is_owned_name(name) is False


def test_metadata_write_survives_a_filesystem_that_cannot_fsync_a_file(tmp_path, monkeypatch):
    import stat

    real_fsync = os.fsync

    def tmpfs_like(fd):
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(22, "Invalid argument")
        real_fsync(fd)

    monkeypatch.setattr("src.core.safe_io.atomic_write.os.fsync", tmpfs_like)
    ledger = _ledger(tmp_path)
    ledger.write_atomic({"owned_tmux_sessions": ["cloude_a"]})
    assert json.loads(ledger.path().read_text()) == {"owned_tmux_sessions": ["cloude_a"]}
