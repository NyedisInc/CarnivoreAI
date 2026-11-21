
from __future__ import annotations

import os
import sys

import pytest

from src.core import relay_keychain as rk
from src.core.key_store import dpapi_store, file_store
from src.core.relay_identity import device_key as dk

SERVICE = rk.DEVICE_KEY_SERVICE
INSTALL = "inst0123456789abcdef"


@pytest.fixture
def store(tmp_path, monkeypatch):
    backend = dpapi_store if sys.platform == "win32" else file_store
    keys = tmp_path / "keys"
    monkeypatch.setattr(file_store, "keys_dir", lambda: keys)
    monkeypatch.setattr(rk, "_key_store_for", lambda service: backend)
    monkeypatch.setattr(rk, "_refused_under_test", lambda service: False)
    return keys


def _only_file(keys):
    files = [p for p in keys.iterdir() if p.suffix == ".key"]
    assert len(files) == 1
    return files[0]


def test_round_trip_and_absent_versus_unavailable(store):
    assert rk.read_password_state(SERVICE, INSTALL) == (rk.READ_ABSENT, None)
    rk.write_password(SERVICE, INSTALL, "first_secret", replace=False)
    with pytest.raises(rk.KeychainWriteError):
        rk.write_password(SERVICE, INSTALL, "second_secret", replace=False)
    assert rk.read_password_state(SERVICE, INSTALL) == (rk.READ_OK, "first_secret")
    rk.write_password(SERVICE, INSTALL + ".next", "staged", replace=True)
    rk.write_password(SERVICE, INSTALL, "replaced", replace=True)
    assert rk.read_password_state(SERVICE, INSTALL) == (rk.READ_OK, "replaced")
    assert rk.delete_password(SERVICE, INSTALL + ".next") is True
    assert rk.read_password_state(SERVICE, INSTALL + ".next") == (rk.READ_ABSENT, None)
    assert rk.read_password_state(SERVICE, "../escape")[0] == rk.READ_UNAVAILABLE

    rk.delete_password(SERVICE, INSTALL)
    first = dk.load_or_create(INSTALL)
    assert dk.load_or_create(INSTALL).device_id == first.device_id

    path = _only_file(store)
    before = path.read_bytes()
    if sys.platform == "win32":
        path.write_bytes(b"not a dpapi blob")
        before = path.read_bytes()
    else:
        os.chmod(path, 0o644)
    assert rk.read_password_state(SERVICE, INSTALL)[0] == rk.READ_UNAVAILABLE
    with pytest.raises(dk.DeviceKeyUnavailable):
        dk.load_or_create(INSTALL)
    assert path.read_bytes() == before
    if sys.platform != "win32":
        os.chmod(path, 0o600)
        link = store / "second-link"
        os.link(path, link)
        assert rk.read_password_state(SERVICE, INSTALL)[0] == rk.READ_UNAVAILABLE
        os.unlink(link)
        path.unlink()
        os.symlink(store / "elsewhere", path)
        assert rk.read_password_state(SERVICE, INSTALL)[0] == rk.READ_UNAVAILABLE
