
from __future__ import annotations

import fcntl
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

import structlog

from src.core.pack.relay import keychain_write
from src.core.provider_ledger import keychain

logger = structlog.get_logger()

LIVE_SERVICE = "gemini"
LIVE_ACCOUNT = "antigravity"
COPY_SERVICE = "Carnivore agy login"
PROVIDER = "antigravity"
LOCK_NAME = "agy-accounts.lock"


class AgyAccountError(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def account_id_for_email(email: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (email or "").lower()).strip("-")[:48].strip("-")
    if not slug:
        raise AgyAccountError("bad_id")
    return "agy-" + slug


def read_live() -> Optional[str]:
    return keychain.read_password(LIVE_SERVICE, account=LIVE_ACCOUNT)


def read_copy(account_id: str) -> Optional[str]:
    return keychain.read_password(COPY_SERVICE, account=account_id)


def has_copy(account_id: str) -> bool:
    return read_copy(account_id) is not None


def _write(service: str, account: str, blob: str) -> None:
    update = keychain.read_password(service, account=account) is not None
    try:
        keychain_write.write_item(service, blob, account=account, update=update)
    except keychain_write.KeychainWriteError as exc:
        logger.warning("agy_account_write_failed", service=service, code=exc.code)
        raise AgyAccountError("write_failed") from None


@contextmanager
def swap_lock(state_dir: Path) -> Iterator[None]:
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    fd = os.open(str(Path(state_dir) / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def snapshot(account_id: str) -> None:
    blob = read_live()
    if blob is None:
        raise AgyAccountError("no_live_login")
    _write(COPY_SERVICE, account_id, blob)
    logger.info("agy_account_snapshot", account_id=account_id)


def forget(account_id: str) -> bool:
    if not has_copy(account_id):
        return False
    try:
        keychain_write.delete_item(COPY_SERVICE, account=account_id)
    except keychain_write.KeychainWriteError as exc:
        logger.warning("agy_account_forget_failed", code=exc.code)
        raise AgyAccountError("write_failed") from None
    return True


def activate(account_id: str, *, current_id: Optional[str], state_dir: Path, move_pointer: Callable[[str], object]) -> None:
    with swap_lock(state_dir):
        target = read_copy(account_id)
        if target is None:
            raise AgyAccountError("no_copy")
        live = read_live()
        if live is not None and current_id and current_id != account_id and has_copy(current_id):
            _write(COPY_SERVICE, current_id, live)
        if live != target:
            _write(LIVE_SERVICE, LIVE_ACCOUNT, target)
        move_pointer(account_id)
    logger.info("agy_account_activated", account_id=account_id, previous=current_id)
