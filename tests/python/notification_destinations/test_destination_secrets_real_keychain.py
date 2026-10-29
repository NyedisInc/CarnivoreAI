
from __future__ import annotations

import asyncio
import os
import secrets as stdlib_secrets
import subprocess
import sys

import pytest

from src.core import relay_keychain
from src.core.notifications.destinations import secrets as sec
from src.core.notifications.destinations.secrets import DestinationSecrets


class _ThrowawayServiceBackend:

    def __init__(self, service: str) -> None:
        self.service = service

    def read_state(self, service: str, account: str):
        return relay_keychain.read_password_state(self.service, account)

    def write(self, service: str, account: str, secret: str) -> None:
        relay_keychain.write_password(self.service, account, secret)

    def delete(self, service: str, account: str) -> bool:
        return relay_keychain.delete_password(self.service, account)


def _keychain_usable(service: str, account: str) -> bool:
    try:
        info = subprocess.run([relay_keychain.SECURITY_BIN, "show-keychain-info"], capture_output=True, timeout=10,
                              check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if info.returncode != 0:
        return False
    state, _ = relay_keychain.read_password_state(service, account)
    return state == relay_keychain.READ_ABSENT


REAL_KEYCHAIN_ENV = "CLOUDE_REAL_KEYCHAIN_TEST"


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists(relay_keychain.SECURITY_BIN),
                    reason="needs the macOS security binary")
@pytest.mark.skipif(os.environ.get(REAL_KEYCHAIN_ENV) != "1",
                    reason=f"opt-in: set {REAL_KEYCHAIN_ENV}=1 (a locked login keychain would pop an unlock dialog)")
def test_real_security_round_trip_of_a_base64url_bundle_under_a_throwaway_service():
    """RED WHEN: the encoded bundle does not survive the real stdin write and `-w` read, or delete leaves it behind."""
    service = f"ai.carnivore.test.notif-secrets-{stdlib_secrets.token_hex(4)}"
    dest = f"d_{stdlib_secrets.token_hex(6)}"
    assert service not in relay_keychain._PRODUCTION_SERVICES and service != sec.SERVICE
    fields = {"url": "https://example.test/hook?q=þÿ>>>???~~~", "token": "ûï¿" * 7}
    encoded = sec.encode(fields)
    assert ("-" in encoded or "_" in encoded) and relay_keychain.is_safe_secret(encoded)
    if not _keychain_usable(service, dest):
        pytest.skip("no usable unlocked default keychain here, so no write is attempted")
    store = DestinationSecrets(backend=_ThrowawayServiceBackend(service))
    run = asyncio.run

    try:
        assert run(store.get(dest)) is None
        run(store.put(dest, fields))
        assert run(store.get(dest)) == fields
        assert run(store.delete(dest)) is True
    finally:
        relay_keychain.delete_password(service, dest)
        leftover = relay_keychain.read_password_state(service, dest)[0]
        assert leftover == relay_keychain.READ_ABSENT, f"throwaway keychain item {service}/{dest} was left behind"
    assert run(store.get(dest)) is None
