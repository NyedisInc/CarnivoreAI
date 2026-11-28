
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.agy import accounts as agy


class FakeKeychain:

    def __init__(self, live=None, copies=None):
        self.live = live
        self.copies = dict(copies or {})
        self.log = []

    def read_live(self):
        return self.live

    def read_copy(self, account_id):
        return self.copies.get(account_id)

    def write(self, service, account, blob):
        self.log.append((service, account, blob))
        if service == agy.LIVE_SERVICE:
            self.live = blob
        else:
            self.copies[account] = blob


@pytest.fixture
def kc(monkeypatch):
    fake = FakeKeychain(live="LIVE-A", copies={"a": "OLD-A", "b": "COPY-B"})
    monkeypatch.setattr(agy, "read_live", fake.read_live)
    monkeypatch.setattr(agy, "read_copy", fake.read_copy)
    monkeypatch.setattr(agy, "_write", fake.write)
    return fake


def test_activate_saves_live_back_before_writing_then_moves_pointer(kc, tmp_path):
    moved = []
    agy.activate("b", current_id="a", state_dir=tmp_path, move_pointer=lambda i: (moved.append((i, list(kc.log))), None)[1])
    assert kc.log == [(agy.COPY_SERVICE, "a", "LIVE-A"), (agy.LIVE_SERVICE, agy.LIVE_ACCOUNT, "COPY-B")]
    assert kc.copies["a"] == "LIVE-A"
    assert moved == [("b", kc.log)]


def test_activate_without_a_copy_writes_nothing(kc, tmp_path):
    moved = []
    with pytest.raises(agy.AgyAccountError) as err:
        agy.activate("zzz", current_id="a", state_dir=tmp_path, move_pointer=moved.append)
    assert err.value.code == "no_copy" and kc.log == [] and moved == []


def test_activate_skips_save_back_for_the_account_already_active(kc, tmp_path):
    kc.live = "COPY-B"
    agy.activate("b", current_id="b", state_dir=tmp_path, move_pointer=lambda i: None)
    assert kc.log == []


def test_a_failed_live_write_leaves_the_pointer_alone(kc, tmp_path, monkeypatch):
    def boom(service, account, blob):
        if service == agy.LIVE_SERVICE:
            raise agy.AgyAccountError("write_failed")
        kc.write(service, account, blob)

    monkeypatch.setattr(agy, "_write", boom)
    moved = []
    with pytest.raises(agy.AgyAccountError):
        agy.activate("b", current_id="a", state_dir=tmp_path, move_pointer=moved.append)
    assert moved == [] and kc.copies["a"] == "LIVE-A"


def test_activate_with_no_live_login_still_writes_the_target(kc, tmp_path):
    kc.live = None
    agy.activate("b", current_id="a", state_dir=tmp_path, move_pointer=lambda i: None)
    assert kc.log == [(agy.LIVE_SERVICE, agy.LIVE_ACCOUNT, "COPY-B")]


def test_snapshot_copies_the_live_blob_and_refuses_with_none(kc):
    agy.snapshot("c")
    assert kc.copies["c"] == "LIVE-A" and kc.log[-1][0] == agy.COPY_SERVICE
    kc.live = None
    with pytest.raises(agy.AgyAccountError) as err:
        agy.snapshot("d")
    assert err.value.code == "no_live_login"


def test_account_id_for_email_is_a_valid_slug():
    from src.config.provider_accounts import ProviderAccount

    account_id = agy.account_id_for_email("Alice.Doe+x@Example.com")
    assert account_id == "agy-alice-doe-x-example-com"
    ProviderAccount(id=account_id, name="x", provider="antigravity")
    with pytest.raises(agy.AgyAccountError):
        agy.account_id_for_email("  ")


def test_secret_is_written_on_stdin_never_argv(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("input")))

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()

    from src.core.pack.relay import keychain_write

    store = {}
    monkeypatch.setattr(keychain_write.subprocess, "run", fake_run)
    monkeypatch.setattr(agy.keychain, "read_password", lambda service, account=None: store.get((service, account)) or ("SECRETBLOB" if calls else None))
    agy._write(agy.COPY_SERVICE, "a", "SECRETBLOB")
    argv, stdin = calls[0]
    assert "SECRETBLOB" not in " ".join(argv) and SECRET_HEX in (stdin or "")


SECRET_HEX = b"SECRETBLOB".hex()
