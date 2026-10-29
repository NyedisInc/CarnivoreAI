
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional, Tuple

import structlog

from src.core.test_write_guard import running_under_test

logger = structlog.get_logger()

SERVICE = "ai.carnivore.relay.legacy-publish-token"

ACCOUNT = "carnivore"

DEVICE_KEY_SERVICE = "ai.carnivore.relay.device-key"

FEDERATION_KEY_SERVICE = "ai.carnivore.federation.key"

CATALOG_GUEST_KEY_SERVICE = "ai.carnivore.catalog.guest-key"

BYOAI_KEY_SERVICE = "carnivore-byoai"

NOTIFICATIONS_SERVICE = "carnivore-notifications"

MESSAGING_SERVICE = "carnivore-messaging"
NATIVE_PUSH_SERVICE = "carnivore-native-push"

TEST_SLOT_ENV = "CARNIVORE_SETTINGS_ENV_FILE"

_PRODUCTION_SERVICES = frozenset(
    {SERVICE, DEVICE_KEY_SERVICE, FEDERATION_KEY_SERVICE, BYOAI_KEY_SERVICE,
     NOTIFICATIONS_SERVICE, CATALOG_GUEST_KEY_SERVICE, NATIVE_PUSH_SERVICE, MESSAGING_SERVICE}
)

READ_OK = "ok"
READ_ABSENT = "absent"
READ_UNAVAILABLE = "unavailable"

_EXIT_NOT_FOUND = 44

SECURITY_BIN = "/usr/bin/security"

TIMEOUT_SECONDS = 5.0

_SAFE_SECRET = re.compile(r"[A-Za-z0-9_.~+/=:-]{1,4096}")


def is_safe_secret(value: str) -> bool:
    return bool(_SAFE_SECRET.fullmatch(value))


class KeychainWriteError(RuntimeError):
    pass


def _refused_under_test(service: str) -> bool:
    if service not in _PRODUCTION_SERVICES:
        return False
    return running_under_test() or bool(os.environ.get(TEST_SLOT_ENV))


def read_password_state(service: str, account: str) -> Tuple[str, Optional[str]]:
    if _refused_under_test(service):
        return READ_UNAVAILABLE, None
    try:
        result = subprocess.run(
            [SECURITY_BIN, "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("relay_keychain_read_failed", error=type(exc).__name__)
        return READ_UNAVAILABLE, None
    if result.returncode != 0:
        absent = result.returncode == _EXIT_NOT_FOUND
        (logger.info if absent else logger.warning)(
            "relay_keychain_item_unread", exit_code=result.returncode)
        return (READ_ABSENT if absent else READ_UNAVAILABLE), None
    value = result.stdout.strip()
    return (READ_OK, value) if value else (READ_ABSENT, None)


def read_password(service: str, account: str) -> Optional[str]:
    return read_password_state(service, account)[1]


def write_password(service: str, account: str, secret: str, replace: bool = True) -> None:
    if _refused_under_test(service):
        raise KeychainWriteError("the production item is refused under test")
    for name, value in (("service", service), ("account", account), ("secret", secret)):
        if not _SAFE_SECRET.fullmatch(value):
            raise KeychainWriteError(f"{name} has characters security -i cannot take")
    update = "-U " if replace else ""
    command = f"add-generic-password {update}-s {service} -a {account} -w {secret}\n"
    try:
        result = subprocess.run(
            [SECURITY_BIN, "-i"], input=command, capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KeychainWriteError(type(exc).__name__) from None
    if result.returncode != 0 or result.stderr.strip():
        raise KeychainWriteError(f"security exited {result.returncode}")


def delete_password(service: str, account: str) -> bool:
    if _refused_under_test(service):
        return False
    try:
        result = subprocess.run(
            [SECURITY_BIN, "delete-generic-password", "-s", service, "-a", account],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def read_publish_token() -> Optional[str]:
    return read_password(SERVICE, ACCOUNT)


def store_publish_token(token: str) -> None:
    write_password(SERVICE, ACCOUNT, token)
