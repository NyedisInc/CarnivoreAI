from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.provider_ledger import accounts_store, poller_scan
from src.core.provider_ledger.default_login import canonical_path
from src.core.session_token_usage.account_resolve import accounts_for_default_login


logger = structlog.get_logger()
_TTL_SECONDS = 120
_DEFAULT_TIER = 0
_MANAGED_TIER = 1


def sessions_seen(profile: Path) -> dict[str, float]:
    seen: dict[str, float] = {}
    try:
        with (profile / "history.jsonl").open("rb") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                sid = row.get("sessionId") if isinstance(row, dict) else None
                stamp = row.get("timestamp") if isinstance(row, dict) else None
                if isinstance(sid, str) and isinstance(stamp, (int, float)):
                    seen[sid] = max(seen.get(sid, 0.0), stamp / 1000)
    except OSError:
        pass
    try:
        with os.scandir(profile / "session-env") as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    seen[entry.name] = max(seen.get(entry.name, 0.0), entry.stat().st_mtime)
    except OSError:
        pass
    return seen


def build_index(accounts: list[ProviderAccount]) -> dict[str, tuple[int, float, str]]:
    index: dict[str, tuple[int, float, str]] = {}
    default_dir = canonical_path("~/.claude")
    default_owner = accounts_for_default_login(accounts, provider="claude")
    plans: list[tuple[Path, int, str]] = []
    for account in accounts:
        if account.provider != "claude":
            continue
        directory = canonical_path(profile_dir_for(account))
        if directory is not None and directory != default_dir:
            plans.append((Path(directory), _MANAGED_TIER, account.id))
    if default_dir is not None and len(default_owner) == 1:
        plans.append((Path(default_dir), _DEFAULT_TIER, default_owner[0].id))
    for directory, tier, account_id in plans:
        for sid, stamp in sessions_seen(directory).items():
            if sid not in index or (tier, stamp) > index[sid][:2]:
                index[sid] = (tier, stamp, account_id)
    return index


class AccountAttribution:

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._index: dict[str, tuple[int, float, str]] = {}
        self._built = 0.0
        self._lock = threading.Lock()

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and time.monotonic() - self._built < _TTL_SECONDS:
                return
            try:
                accounts = poller_scan.with_auto_default(accounts_store.list_accounts(self.config_path))
                self._index = build_index(accounts)
            except (OSError, ValueError) as exc:
                logger.warning("stats_account_index_failed", error_type=type(exc).__name__)
            self._built = time.monotonic()

    def __call__(self, provider: str, conversation_id: str) -> str | None:
        if provider != "claude":
            return None
        self.refresh()
        hit = self._index.get(conversation_id.split(":", 1)[0])
        return hit[2] if hit else None
