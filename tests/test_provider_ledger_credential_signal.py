
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pcs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pcs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, ProviderAccount
from src.core.provider_ledger import credential_signal
from src.core.provider_ledger.codex_credentials import CODEX_AUTH_FILE
from src.core.provider_ledger.credentials import CLAUDE_IDENTITY_FILE


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return tmp_path


def claude_account(config_dir: str) -> ProviderAccount:
    return ProviderAccount(
        id="max-main", name="Max main", provider="claude", claude_config_dir=config_dir
    )


def codex_account(codex_home: str) -> ProviderAccount:
    return ProviderAccount(
        id="codex-main", name="Codex main", provider="codex", codex_home=codex_home
    )


class TestSignalPathsNamesTheRightFiles:

    def test_a_custom_claude_profile_watches_its_own_identity_file_and_dir(
        self, home
    ) -> None:
        config_dir = home / ".claude-work"
        config_dir.mkdir()

        paths = credential_signal.signal_paths(claude_account(str(config_dir)))

        assert paths == [config_dir / CLAUDE_IDENTITY_FILE, config_dir]

    def test_the_default_claude_profile_watches_home_dot_claude_json(
        self, home
    ) -> None:
        (home / ".claude").mkdir()

        paths = credential_signal.signal_paths(claude_account(DEFAULT_CLAUDE_CONFIG_DIR))

        assert paths[0] == home / CLAUDE_IDENTITY_FILE
        assert paths[1] == home / ".claude"

    def test_a_codex_account_watches_auth_json_and_its_home_dir(self, home) -> None:
        codex_home = home / ".codex-work"
        codex_home.mkdir()

        paths = credential_signal.signal_paths(codex_account(str(codex_home)))

        assert paths == [codex_home / CODEX_AUTH_FILE, codex_home]

    def test_a_managed_row_watches_its_managed_directory_not_a_hand_edited_pointer(
        self, home
    ) -> None:
        account = ProviderAccount(
            id="claude1",
            name="Managed one",
            provider="claude",
            claude_config_dir="~/.claude-not-the-real-one",
            managed=True,
        )

        paths = credential_signal.signal_paths(account)

        assert str(paths[1]).endswith(
            os.path.join(".carnivore", "accounts", "claude1")
        )
        assert "claude-not-the-real-one" not in str(paths[1])


class TestSignalStampNeverRaises:

    def test_an_absent_path_stamps_none(self, tmp_path) -> None:
        missing = tmp_path / "nope.json"

        assert credential_signal.signal_stamp([missing]) == (None,)

    def test_an_existing_file_stamps_its_mtime_and_size(self, tmp_path) -> None:
        target = tmp_path / "auth.json"
        target.write_text(json.dumps({"a": 1}))

        stamp = credential_signal.signal_stamp([target])

        assert len(stamp) == 1
        mtime_ns, size = stamp[0]
        assert isinstance(mtime_ns, int) and mtime_ns > 0
        assert size == target.stat().st_size

    def test_a_changed_file_stamps_differently(self, tmp_path) -> None:
        target = tmp_path / "auth.json"
        target.write_text(json.dumps({"a": 1}))
        first = credential_signal.signal_stamp([target])

        target.write_text(json.dumps({"a": 1, "b": 2}))
        second = credential_signal.signal_stamp([target])

        assert first != second

    def test_a_path_whose_parent_is_gone_stamps_none_not_a_raise(
        self, tmp_path
    ) -> None:
        ghost = tmp_path / "does-not-exist" / "auth.json"

        assert credential_signal.signal_stamp([ghost]) == (None,)

    def test_an_os_error_other_than_missing_still_stamps_none(
        self, tmp_path, monkeypatch
    ) -> None:
        target = tmp_path / "auth.json"
        target.write_text("{}")

        def deny(self, *args, **kwargs):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "stat", deny)

        assert credential_signal.signal_stamp([target]) == (None,)

    def test_order_and_length_match_the_input(self, tmp_path) -> None:
        present = tmp_path / "a.json"
        present.write_text("x")
        absent = tmp_path / "b.json"

        stamps = credential_signal.signal_stamp([present, absent])

        assert len(stamps) == 2
        assert stamps[0] is not None
        assert stamps[1] is None
