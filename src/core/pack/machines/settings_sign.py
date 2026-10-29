
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.pack.machines import settings_doc
from src.core.relay_identity.device_key import DeviceKey, DeviceKeyUnavailable, b64url, unb64url

logger = structlog.get_logger()

SIGN_PREFIX = b"carnivore pack settings v1\x00"
KEY_TTL_SECONDS = 600.0

ACCEPT = "accept"
ACCEPT_TOFU = "accept_tofu"
LEGACY = "legacy"
LEGACY_SIGNED = "legacy_signed"
IGNORE = "ignore"
REFUSE_UNSIGNED = "unsigned"
REFUSE_MALFORMED = "malformed"
REFUSE_UNPINNED = "unpinned"
REFUSE_BAD_SIGNATURE = "bad_signature"
REFUSE_NOT_ALPHA = "not_alpha"
REASON_NOT_NEWER = "not newer"
REASON_EQUIVOCATION = "equal version, different content"
ACCEPTED = frozenset({ACCEPT, ACCEPT_TOFU, LEGACY, LEGACY_SIGNED})
SIGNED_MODE_ON = frozenset({ACCEPT, ACCEPT_TOFU})


@dataclass(frozen=True)
class Signature:

    signer: str
    sig: str

    def to_dict(self) -> dict:
        return {"signer": self.signer, "sig": self.sig}


def signature_from(raw: Any) -> Optional[Signature]:
    if not isinstance(raw, dict):
        return None
    signer, sig = raw.get("signer"), raw.get("sig")
    if not isinstance(signer, str) or not 0 < len(signer) <= 64 or unb64url(sig, 64) is None:
        return None
    return Signature(signer, sig)


def signed_bytes(doc: settings_doc.PackSettings) -> bytes:
    body = json.dumps(doc.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return SIGN_PREFIX + body.encode("ascii")


def sign(doc: settings_doc.PackSettings, key: DeviceKey, signer: str) -> Signature:
    if doc.rev[1] != signer:
        raise ValueError("only the editor named in rev signs a document")
    return Signature(signer, key.sign(signed_bytes(doc)))


def verify(doc: settings_doc.PackSettings, signature: Signature, public_key_b64: str) -> bool:
    raw_sig, raw_pub = unb64url(signature.sig, 64), unb64url(public_key_b64, 32)
    if raw_sig is None or raw_pub is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(raw_sig, signed_bytes(doc))
    except (InvalidSignature, ValueError):
        return False
    return True


@dataclass(frozen=True)
class Verdict:

    outcome: str
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.outcome in ACCEPTED

    @property
    def refused(self) -> bool:
        return not self.accepted and self.outcome != IGNORE


def judge(*, held: settings_doc.PackSettings, remote: settings_doc.PackSettings, signature: Optional[Signature], self_id: str,
          signed_mode: bool, anchor: str, public_key_for: Callable[[str], Optional[str]]) -> Verdict:
    if signature is None:
        if not settings_doc.newer(remote, held):
            return Verdict(IGNORE, REASON_NOT_NEWER)
        return Verdict(REFUSE_UNSIGNED, "unsigned after signing began") if signed_mode else Verdict(LEGACY, "unsigned, before signing began")
    if signature.signer != remote.rev[1]:
        return Verdict(REFUSE_MALFORMED, "signer is not the editor in rev")
    first = not signed_mode and signature.signer == anchor
    if first and settings_doc.digest(remote) == settings_doc.digest(held):
        return Verdict(IGNORE, REASON_NOT_NEWER)
    if not first and remote.rev[0] <= held.rev[0]:
        same = remote.rev[0] == held.rev[0] and settings_doc.digest(remote) != settings_doc.digest(held)
        return Verdict(IGNORE, REASON_EQUIVOCATION if same else REASON_NOT_NEWER)
    public_key = public_key_for(signature.signer)
    if public_key is None:
        return Verdict(REFUSE_UNPINNED, "signer is not paired here")
    if not verify(remote, signature, public_key):
        return Verdict(REFUSE_BAD_SIGNATURE, "signature does not verify")
    if not first and signature.signer not in (held.master_install_id, self_id):
        return Verdict(REFUSE_NOT_ALPHA, "signer is not the alpha held here")
    if signed_mode:
        return Verdict(ACCEPT)
    if first or signature.signer == self_id:
        return Verdict(ACCEPT_TOFU, "first signed document, from the trust anchor")
    return Verdict(LEGACY_SIGNED, "signed by the alpha held here, which is not the trust anchor")


class Signing:

    def __init__(self, *, install_id: str, load_key: Callable[[], DeviceKey], pinned_key: Callable[[str], Optional[str]],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.install_id = install_id
        self._load_key, self._pinned_key, self._clock = load_key, pinned_key, clock
        self._cached: Optional[tuple[float, DeviceKey]] = None

    def key(self) -> DeviceKey:
        if self._cached is None or self._clock() - self._cached[0] >= KEY_TTL_SECONDS:
            self._cached = (self._clock(), self._load_key())
        return self._cached[1]

    def public_key_for(self, install_id: str) -> Optional[str]:
        if install_id != self.install_id:
            return self._pinned_key(install_id)
        try:
            return b64url(self.key().raw_pub)
        except DeviceKeyUnavailable as exc:
            logger.warning("pack_settings_own_key_unavailable", error_type=type(exc).__name__)
            return None

    def sign(self, doc: settings_doc.PackSettings) -> Signature:
        return sign(doc, self.key(), self.install_id)
