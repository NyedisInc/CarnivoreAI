
from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

from src.core import relay_keychain
from src.core.db import DatastoreUnreadableError, connect, db_path_for, get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.relay_identity.device_key import DeviceKey, DeviceKeyUnavailable, b64url, device_id_for, load_or_create, load_or_create_file

logger = structlog.get_logger()

__all__ = ["DeviceKey", "DeviceKeyUnavailable", "load_key", "fid_for", "public_key_b64", "local_fid",
           "begin_rotation", "commit_rotation"]


SLOT_KEY_FILE = "federation-device.key"


def load_key(install_id: str, **seams) -> DeviceKey:
    """This install's federation key, minting one only when the Keychain says absent.

    Description: a testsrv slot server (``relay_keychain.TEST_SLOT_ENV`` set; its private HOME has
      no login Keychain) keeps the key in a 0600 file in its state dir instead, so slot-to-slot
      pairing works. Production never takes that branch. A call with test seams stays on the
      Keychain code path.

    Inputs: install_id (str); seams - ``read``/``write`` test seams.
    Output: DeviceKey.
    Raises: DeviceKeyUnavailable - the Keychain did not answer or holds junk.
    Example: key = load_key(install_id); key.sign(b"x")
    """
    if not seams and os.environ.get(relay_keychain.TEST_SLOT_ENV):
        from src.config import settings
        try:
            path = settings.get_state_dir() / SLOT_KEY_FILE
        except (OSError, RuntimeError) as exc:
            raise DeviceKeyUnavailable("the slot state directory is unavailable") from exc
        return load_or_create_file(install_id, str(path))
    return load_or_create(install_id, service=relay_keychain.FEDERATION_KEY_SERVICE, **seams)


NEXT_SUFFIX = ".next"


def begin_rotation(install_id: str, *, write=relay_keychain.write_password) -> DeviceKey:
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
