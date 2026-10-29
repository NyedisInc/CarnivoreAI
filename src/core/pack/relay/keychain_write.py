
from __future__ import annotations

import getpass
import subprocess
from typing import Optional

import structlog

from src.core.provider_ledger import keychain

logger = structlog.get_logger()

SECURITY_BIN = "/usr/bin/security"
TIMEOUT_SECONDS = 10.0
MAX_LINE = 3800


class KeychainWriteError(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def keychain_account() -> str:
    return getpass.getuser()


def _quoted(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise KeychainWriteError("bad_value")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _run(command: str, service: str, security_bin: str) -> None:
    if len(command) > MAX_LINE:
        raise KeychainWriteError("too_large")
    try:
        completed = subprocess.run([security_bin, "-i"], input=command, capture_output=True, text=True,
                                   timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("relay_keychain_write_timeout", service=service)
        raise KeychainWriteError("timeout") from None
    except OSError as exc:
        logger.warning("relay_keychain_write_unavailable", service=service, error=type(exc).__name__)
        raise KeychainWriteError("unavailable") from None
    if completed.returncode != 0:
        logger.warning("relay_keychain_write_failed", service=service, status=completed.returncode)
        raise KeychainWriteError("failed")


def write_item(service: str, document: str, *, account: Optional[str] = None, update: bool = False,
               security_bin: str = SECURITY_BIN) -> None:
    who = account or keychain_account()
    flag = "-U " if update else ""
    _run(f"add-generic-password {flag}-s {_quoted(service)} -a {_quoted(who)} -X {document.encode('utf-8').hex()}\n",
         service, security_bin)
    if keychain.read_password(service, account=who) != document:
        logger.warning("relay_keychain_write_not_verified", service=service)
        raise KeychainWriteError("not_verified")
    logger.info("relay_keychain_written", service=service)


def delete_item(service: str, *, account: Optional[str] = None, security_bin: str = SECURITY_BIN) -> None:
    who = account or keychain_account()
    _run(f"delete-generic-password -s {_quoted(service)} -a {_quoted(who)}\n", service, security_bin)
    if keychain.read_password(service, account=who) is not None:
        logger.warning("relay_keychain_delete_not_verified", service=service)
        raise KeychainWriteError("not_verified")
    logger.info("relay_keychain_deleted", service=service)
