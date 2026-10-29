
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets as _random
import subprocess
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Optional, Tuple

import structlog

from src.core import relay_keychain
from src.core.notifications.destinations import secrets as blob
from src.core.test_write_guard import running_under_test

log = structlog.get_logger(__name__)

SERVICE = relay_keychain.MESSAGING_SERVICE

_PROVIDER_ID = re.compile(r"p_[0-9a-f]{12}")
_CONV_FIELD = "conv_"

_OP_REF = re.compile(r"op://[A-Za-z0-9 _.\-]+/[A-Za-z0-9 _.\-]+/[A-Za-z0-9 _.\-]+(?:/[A-Za-z0-9 _.\-]+)?")

OP_BINARIES: Tuple[str, ...] = ("/opt/homebrew/bin/op", "/usr/local/bin/op")

OP_TIMEOUT_SECONDS = 60.0

SecretError = blob.SecretError
SecretStoreUnavailable = blob.SecretStoreUnavailable
CorruptSecret = blob.CorruptSecret


class OpReadError(Exception):
    """An ``op://`` reference could not be read. ``str()`` is a fixed reason, never the value or the CLI's output."""


def check_provider_id(provider_id: str) -> str:
    if not isinstance(provider_id, str) or not _PROVIDER_ID.fullmatch(provider_id):
        raise blob.InvalidDestinationId("provider id must be p_ plus 12 lowercase hex characters")
    return provider_id


@dataclass(frozen=True)
class ProviderSecrets:

    base_url: str
    token: str
    owner_senders: Tuple[str, ...]
    match_key: str
    conversations: Dict[str, str] = field(default_factory=dict)

    def fields(self) -> Dict[str, str]:
        out = {"base_url": self.base_url, "token": self.token, "owner_senders": "\n".join(self.owner_senders),
               "match_key": self.match_key}
        out.update({_CONV_FIELD + cid: conv for cid, conv in self.conversations.items()})
        return out

    def with_conversation(self, conversation_id: str, conversation: str) -> "ProviderSecrets":
        """A copy with one more conversation id. Output: ProviderSecrets."""
        return replace(self, conversations={**self.conversations, conversation_id: conversation})

    def without_conversation(self, conversation_id: str) -> "ProviderSecrets":
        """A copy with one conversation id removed. Output: ProviderSecrets."""
        return replace(self, conversations={k: v for k, v in self.conversations.items() if k != conversation_id})


def new_match_key() -> str:
    return _random.token_hex(32)


def match_of(match_key: str, conversation: str) -> str:
    """The HMAC a conversation row stores instead of the provider conversation id. Output: str (64 hex).

    Example: match_of(key, "any;-;+15555550100") == match_of(key, "any;-;+15555550100")
    """
    return hmac.new(match_key.encode("utf-8"), conversation.encode("utf-8"), hashlib.sha256).hexdigest()


def _from_fields(fields: Dict[str, str]) -> ProviderSecrets:
    try:
        return ProviderSecrets(
            base_url=fields["base_url"], token=fields["token"],
            owner_senders=tuple(h for h in fields.get("owner_senders", "").split("\n") if h),
            match_key=fields["match_key"],
            conversations={k[len(_CONV_FIELD):]: v for k, v in fields.items() if k.startswith(_CONV_FIELD)},
        )
    except KeyError:
        raise CorruptSecret("the stored messaging secret is missing a field") from None


class MessagingSecrets:

    def __init__(self, *, backend: Optional[blob.KeychainBackend] = None, service: str = SERVICE) -> None:
        self._store = blob.DestinationSecrets(backend=backend, service=service, check_id=check_provider_id,
                                              event="messaging_secret")

    async def load(self, provider_id: str) -> Optional[ProviderSecrets]:
        fields = await self._store.get(provider_id)
        return _from_fields(fields) if fields is not None else None

    async def save(self, provider_id: str, value: ProviderSecrets) -> bool:
        try:
            return await self._store.put_verified(provider_id, value.fields())
        except (blob.InvalidFields, blob.SecretTooLarge) as exc:
            log.warning("messaging_secret_refused", provider_id=provider_id, error_type=type(exc).__name__)
            return False

    async def delete(self, provider_id: str) -> bool:
        return await self._store.delete(provider_id)


Runner = Callable[[list], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: list) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, capture_output=True, text=True, timeout=OP_TIMEOUT_SECONDS, check=False)


def _op_binary() -> Optional[str]:
    return next((p for p in OP_BINARIES if os.path.isfile(p) and os.access(p, os.X_OK)), None)


def read_op_reference_sync(ref: str, *, runner: Optional[Runner] = None) -> str:
    if not isinstance(ref, str) or not _OP_REF.fullmatch(ref):
        raise OpReadError("not an op:// reference")
    if runner is None and running_under_test():
        raise OpReadError("op reads are refused under test")
    binary = _op_binary() if runner is None else "op"
    if binary is None:
        raise OpReadError("the 1Password CLI is not installed")
    try:
        result = (runner or _default_runner)([binary, "read", "--no-newline", ref])
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("messaging_op_read_failed", error_type=type(exc).__name__)
        raise OpReadError("the 1Password CLI did not answer") from None
    value = (result.stdout or "").strip()
    if result.returncode != 0 or not value:
        log.warning("messaging_op_read_failed", exit_code=result.returncode)
        raise OpReadError("the 1Password CLI refused the read")
    return value


async def read_op_reference(ref: str, *, runner: Optional[Runner] = None) -> str:
    return await asyncio.to_thread(read_op_reference_sync, ref, runner=runner)
