
from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Optional

import pytest
import structlog
from structlog.testing import capture_logs

from src.core import relay_keychain
from src.core.notifications.destinations import secrets as sec
from src.core.notifications.destinations.secrets import DestinationSecrets

DEST = "d_0123456789ab"
SENTINEL = "SENTINEL-xyzzy-9f3a"


class FakeKeychain:

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.tamper: Optional[str] = None
        self.state: Optional[str] = None

    def read_state(self, service, account):
        if self.state:
            return self.state, None
        if self.tamper is not None:
            return relay_keychain.READ_OK, self.tamper
        v = self.items.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret):
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


def run(coro):
    return asyncio.run(coro)


def make():
    kc = FakeKeychain()
    return kc, DestinationSecrets(backend=kc)


def test_round_trip_and_delete():
    kc, store = make()
    fields = {"url": f"https://h/{SENTINEL}", "chat_id": "42"}
    run(store.put(DEST, fields))
    assert ("carnivore-notifications", DEST) in kc.items
    assert relay_keychain.is_safe_secret(kc.items[("carnivore-notifications", DEST)])
    assert run(store.get(DEST)) == fields
    assert run(store.delete(DEST)) is True
    assert run(store.get(DEST)) is None
    assert run(store.delete(DEST)) is False


@pytest.mark.parametrize("bad", ["webpush:x", "", "d_0123456789A", "d_0123456789a", "../d_0123456789ab", "d_0123456789ab/x", "x_0123456789ab", "d_0123456789abc"])
def test_bad_ids_refused(bad):
    kc, store = make()
    for call in (store.put(bad, {"a": "b"}), store.get(bad), store.delete(bad), store.put_verified(bad, {"a": "b"})):
        with pytest.raises(sec.InvalidDestinationId):
            run(call)
    assert kc.items == {}


def test_oversize_and_bad_fields_refused():
    kc, store = make()
    with pytest.raises(sec.SecretTooLarge):
        run(store.put(DEST, {"url": "x" * 5000}))
    with pytest.raises(sec.InvalidFields):
        run(store.put(DEST, {"Bad Name": "x"}))
    with pytest.raises(sec.InvalidFields):
        run(store.put(DEST, {"n": 5}))  # type: ignore[dict-item]
    assert kc.items == {}


@pytest.mark.parametrize("junk", ["!!!", "bm90anNvbg==", "e30=", "eyJ2IjoyLCJmaWVsZHMiOnt9fQ==", "eyJ2IjoxLCJmaWVsZHMiOnsiYSI6MX19"])
def test_corrupt_value_raises_named_error(junk):
    kc, store = make()
    kc.items[("carnivore-notifications", DEST)] = junk
    with pytest.raises(sec.CorruptSecret):
        run(store.get(DEST))


def test_unavailable_keychain_is_not_absent():
    kc, store = make()
    kc.state = relay_keychain.READ_UNAVAILABLE
    with pytest.raises(sec.SecretStoreUnavailable):
        run(store.get(DEST))
    assert run(store.put_verified(DEST, {"a": "b"})) is False


def test_put_verified_true_then_false_on_mismatch_and_refused_write():
    kc, store = make()
    assert run(store.put_verified(DEST, {"a": "b"})) is True
    kc.tamper = sec.encode({"a": "different"})
    assert run(store.put_verified(DEST, {"a": "b"})) is False
    kc.tamper = "garbage!!"
    assert run(store.put_verified(DEST, {"a": "b"})) is False

    class Refuses(FakeKeychain):
        def write(self, service, account, secret):
            raise relay_keychain.KeychainWriteError("no")

    assert run(DestinationSecrets(backend=Refuses()).put_verified(DEST, {"a": "b"})) is False


def test_merge_blank_means_untouched():
    old = {"url": "u1", "token": "t1"}
    assert sec.merge(old, {"url": "", "token": "t2", "new": "n"}) == {"url": "u1", "token": "t2", "new": "n"}
    assert sec.merge(old, {"url": "   ", "token": None}) == old
    assert sec.merge(None, {"a": "b"}) == {"a": "b"}
    assert old == {"url": "u1", "token": "t1"}


def test_notifications_service_is_a_guarded_production_service():
    svc = relay_keychain.NOTIFICATIONS_SERVICE
    assert svc == "carnivore-notifications" and svc in relay_keychain._PRODUCTION_SERVICES
    state, value = relay_keychain.read_password_state(svc, DEST)
    assert state == relay_keychain.READ_UNAVAILABLE and value is None
    with pytest.raises(relay_keychain.KeychainWriteError):
        relay_keychain.write_password(svc, DEST, "abc")


def test_sentinel_never_in_argv_logs_or_exceptions(monkeypatch, caplog):
    calls = []

    def fake_run(argv, **kw):
        calls.append((list(argv), kw.get("input")))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(relay_keychain, "_refused_under_test", lambda service: False)
    monkeypatch.setattr(relay_keychain.subprocess, "run", fake_run)
    store = DestinationSecrets()
    caplog.set_level(logging.DEBUG)
    with capture_logs() as events:
        run(store.put(DEST, {"url": SENTINEL}))
        run(store.delete(DEST))
        with pytest.raises(sec.SecretError) as exc_info:
            run(store.put(DEST, {"url": SENTINEL * 500}))
        def failing(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"quoted {SENTINEL}")

        monkeypatch.setattr(relay_keychain.subprocess, "run", failing)
        with pytest.raises(sec.SecretStoreUnavailable) as exc2:
            run(store.put(DEST, {"url": SENTINEL}))
    assert calls, "the real subprocess path was not exercised"
    encoded = sec.encode({"url": SENTINEL})
    assert any(encoded in (stdin or "") for _, stdin in calls), "value must travel on stdin"
    for argv, _ in calls:
        assert SENTINEL not in " ".join(argv) and encoded not in " ".join(argv)
    blob = repr(events) + caplog.text + str(exc_info.value) + str(exc2.value) + repr(exc2.value.__cause__)
    assert SENTINEL not in blob and encoded not in blob
    assert any(e.get("dest_id") == DEST and e.get("fields") == ["url"] for e in events), "logs should carry id and names"
