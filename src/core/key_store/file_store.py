
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Optional, Tuple

import structlog

from src.core import relay_keychain

logger = structlog.get_logger()

_SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,200}")

_MAX_BYTES = 65536

_POSIX = os.name == "posix"


def keys_dir() -> Path:
    from src.config import settings
    return settings.get_state_dir() / "keys"


def item_name(service: str, account: str) -> Optional[str]:
    if not (_SAFE_NAME.fullmatch(service) and _SAFE_NAME.fullmatch(account)):
        return None
    return f"{service}__{account}.key"


def _ensure_dir(base: Path) -> None:
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        info = os.lstat(base)
    except OSError as exc:
        raise relay_keychain.KeychainWriteError("the key directory could not be created") from exc
    if _POSIX:
        import stat
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise relay_keychain.KeychainWriteError("the key directory is not private to this user")


def read_blob(base: Path, name: str) -> Tuple[str, Optional[bytes]]:
    path = base / name
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return relay_keychain.READ_ABSENT, None
    except OSError as exc:
        logger.warning("key_store_file_unreadable", why=type(exc).__name__)
        return relay_keychain.READ_UNAVAILABLE, None
    try:
        import stat
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES or info.st_size == 0:
            logger.warning("key_store_file_refused", why="not a plain key file")
            return relay_keychain.READ_UNAVAILABLE, None
        if _POSIX and (info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1):
            logger.warning("key_store_file_refused", why="owner, mode or link count")
            return relay_keychain.READ_UNAVAILABLE, None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(_MAX_BYTES + 1)
    except OSError as exc:
        logger.warning("key_store_file_unreadable", why=type(exc).__name__)
        return relay_keychain.READ_UNAVAILABLE, None
    finally:
        os.close(fd)
    return relay_keychain.READ_OK, data


def write_blob(base: Path, name: str, data: bytes, replace: bool) -> None:
    _ensure_dir(base)
    tmp = base / f".{name}.{secrets.token_hex(8)}.tmp"
    target = base / name
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(tmp, target)
        else:
            os.link(tmp, target)
    except FileExistsError:
        raise relay_keychain.KeychainWriteError("the item already exists") from None
    except OSError as exc:
        raise relay_keychain.KeychainWriteError(type(exc).__name__) from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def delete_blob(base: Path, name: str) -> bool:
    try:
        os.unlink(base / name)
    except OSError:
        return False
    return True


def target_for(service: str, account: str) -> Optional[Tuple[Path, str]]:
    name = item_name(service, account)
    if name is None:
        return None
    try:
        return keys_dir(), name
    except RuntimeError as exc:
        logger.warning("key_store_dir_unavailable", why=type(exc).__name__)
        return None


def read_state(service: str, account: str) -> Tuple[str, Optional[str]]:
    target = target_for(service, account)
    if target is None:
        return relay_keychain.READ_UNAVAILABLE, None
    state, data = read_blob(*target)
    if state != relay_keychain.READ_OK or data is None:
        return state, None
    try:
        return relay_keychain.READ_OK, data.decode("ascii")
    except UnicodeDecodeError:
        return relay_keychain.READ_UNAVAILABLE, None


def write(service: str, account: str, secret: str, replace: bool) -> None:
    target = target_for(service, account)
    if target is None or not relay_keychain.is_safe_secret(secret):
        raise relay_keychain.KeychainWriteError("the item name or value is not storable")
    write_blob(target[0], target[1], secret.encode("ascii"), replace)


def delete(service: str, account: str) -> bool:
    target = target_for(service, account)
    return target is not None and delete_blob(*target)
