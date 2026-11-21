
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core.claude_config import accounts_folder_cache, profile_roots
from src.core.provider_ledger import relay_accounts

RELAY = "0123456789ab-work-relay"
CODEX_RELAY = "0123456789ab-work-relay-codex"


@pytest.fixture()
def accounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "accounts"
    root.mkdir()
    monkeypatch.setenv(accounts_folder_cache.ACCOUNTS_DIR_ENV, str(root))
    accounts_folder_cache.clear()
    yield root
    accounts_folder_cache.clear()


@pytest.fixture()
def scandirs(monkeypatch: pytest.MonkeyPatch, accounts: Path) -> List[str]:
    seen: List[str] = []
    real = Path.glob

    def spy(self: Path, pattern: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(self) == str(accounts):
            seen.append(pattern)
        return real(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", spy)
    return seen


def test_unchanged_folder_is_listed_once(accounts: Path, scandirs: List[str]) -> None:
    (accounts / RELAY).mkdir()
    (accounts / CODEX_RELAY).mkdir()
    for _ in range(20):
        assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]
        assert [a.id for a in relay_accounts.codex_relay_accounts()] == [CODEX_RELAY]
        assert [p.name for p in profile_roots._relay_profile_dirs()] == [RELAY]
    assert len(scandirs) == 2


def test_added_and_removed_profiles_show_up(accounts: Path) -> None:
    assert relay_accounts.relay_accounts() == []
    (accounts / RELAY).mkdir()
    assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]
    (accounts / CODEX_RELAY).mkdir()
    assert [a.id for a in relay_accounts.codex_relay_accounts()] == [CODEX_RELAY]
    (accounts / RELAY).rmdir()
    assert relay_accounts.relay_accounts() == []
    (accounts / CODEX_RELAY).rename(accounts / "0123456789ab-other-relay-codex")
    assert [a.id for a in relay_accounts.codex_relay_accounts()] == ["0123456789ab-other-relay-codex"]


def test_missing_folder_is_not_remembered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "later"
    monkeypatch.setenv(accounts_folder_cache.ACCOUNTS_DIR_ENV, str(root))
    accounts_folder_cache.clear()
    assert relay_accounts.relay_accounts() == []
    (root / RELAY).mkdir(parents=True)
    assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]


def test_replaced_folder_misses(accounts: Path, tmp_path: Path) -> None:
    (accounts / RELAY).mkdir()
    assert len(relay_accounts.relay_accounts()) == 1
    accounts.rename(tmp_path / "old")
    accounts.mkdir()
    assert relay_accounts.relay_accounts() == []


def test_cache_is_bounded(accounts: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accounts_folder_cache, "MAX_ENTRIES", 3)
    for i in range(10):
        accounts_folder_cache.listed_dirs("x%d-*" % i)
    assert len(accounts_folder_cache._listings) <= 3


def test_restored_mtime_does_not_hide_a_new_folder(accounts: Path) -> None:
    assert relay_accounts.relay_accounts() == []
    before = accounts.stat()
    (accounts / RELAY).mkdir()
    os.utime(accounts, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert accounts.stat().st_mtime_ns == before.st_mtime_ns
    assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]


def test_unreadable_folder_is_rechecked_after_chmod(accounts: Path) -> None:
    (accounts / RELAY).mkdir()
    before = accounts.stat()
    os.chmod(accounts, 0o300)
    try:
        relay_accounts.relay_accounts()
    finally:
        os.chmod(accounts, 0o755)
    os.utime(accounts, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]


def test_symlinked_profile_whose_target_is_gone_drops_out(accounts: Path, tmp_path: Path) -> None:
    target = tmp_path / "real-profile"
    target.mkdir()
    (accounts / RELAY).symlink_to(target, target_is_directory=True)
    assert [a.id for a in relay_accounts.relay_accounts()] == [RELAY]
    target.rmdir()
    assert relay_accounts.relay_accounts() == []


def test_keep_filter_is_not_part_of_what_is_remembered(accounts: Path) -> None:
    (accounts / RELAY).mkdir()
    (accounts / "0123456789ab-x-relay").mkdir()
    both = accounts_folder_cache.listed_dirs(relay_accounts.RELAY_GLOB)
    only = accounts_folder_cache.listed_dirs(relay_accounts.RELAY_GLOB, lambda n: "work" in n)
    assert len(both) == 2 and [p.name for p in only] == [RELAY]
