
from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional, Tuple

import structlog

from src.core import relay_keychain
from src.core.db import DatastoreUnreadableError, connect, db_path_for, get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.relay_identity.device_key import (
    DeviceKey, DeviceKeyUnavailable, b64url, device_id_for, load_or_create, load_or_create_file, unb64url,
)

logger = structlog.get_logger()

__all__ = ["DeviceKey", "DeviceKeyUnavailable", "load_key", "fid_for", "public_key_b64", "local_fid",
           "begin_rotation", "commit_rotation"]


SLOT_KEY_FILE = "federation-device.key"


def load_key(install_id: str, **seams) -> DeviceKey:
    if not seams and os.environ.get(relay_keychain.TEST_SLOT_ENV):
        from src.config import settings
        try:
            path = settings.get_state_dir() / SLOT_KEY_FILE
        except (OSError, RuntimeError) as exc:
            raise DeviceKeyUnavailable("the slot state directory is unavailable") from exc
        return load_or_create_file(install_id, str(path))
    return load_or_create(install_id, service=relay_keychain.FEDERATION_KEY_SERVICE, **seams)


NEXT_SUFFIX = ".next"


def begin_rotation(install_id: str, *, write: Callable[..., None] = relay_keychain.write_password,
                   read: Callable[[str, str], Tuple[str, Optional[str]]] = relay_keychain.read_password_state) -> DeviceKey:
    state, staged = read(relay_keychain.FEDERATION_KEY_SERVICE, install_id + NEXT_SUFFIX)
    if state == relay_keychain.READ_OK and staged is not None:
        resumed = unb64url(staged, 32)
        if resumed is not None:
            return DeviceKey.from_seed(resumed)
    elif state != relay_keychain.READ_ABSENT:
        raise DeviceKeyUnavailable("the login keychain did not answer")
    seed = secrets.token_bytes(32)
    try:
        write(relay_keychain.FEDERATION_KEY_SERVICE, install_id + NEXT_SUFFIX, b64url(seed), replace=True)
    except relay_keychain.KeychainWriteError:
        raise DeviceKeyUnavailable("the login keychain refused the new key") from None
    return DeviceKey.from_seed(seed)


def commit_rotation(install_id: str, *, read=relay_keychain.read_password_state, write=relay_keychain.write_password,
                    delete=relay_keychain.delete_password) -> None:
    state, seed = read(relay_keychain.FEDERATION_KEY_SERVICE, install_id + NEXT_SUFFIX)
    if state != relay_keychain.READ_OK or seed is None:
        raise DeviceKeyUnavailable("no staged federation key")
    try:
        write(relay_keychain.FEDERATION_KEY_SERVICE, install_id, seed, replace=True)
    except relay_keychain.KeychainWriteError:
        raise DeviceKeyUnavailable("the login keychain refused the new key") from None
    delete(relay_keychain.FEDERATION_KEY_SERVICE, install_id + NEXT_SUFFIX)


def fid_for(raw_pub: bytes) -> str:
    return device_id_for(raw_pub)


def public_key_b64(key: DeviceKey) -> str:
    return b64url(key.raw_pub)


def local_fid(state_dir: Path, **seams) -> Optional[str]:
    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            install_id = get_meta(conn, META_INSTALL_ID)
        if not install_id:
            return None
        return fid_for(load_key(install_id, **seams).raw_pub)
    except (DeviceKeyUnavailable, DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning("federation_fid_unavailable", error_type=type(exc).__name__)
        return None
