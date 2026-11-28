
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from src.core.pack.machines import capabilities
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.machines.settings_sign import Signature, Signing, verify_bytes
from src.core.relay_identity.device_key import DeviceKeyUnavailable

DATA_PREFIX = b"carnivore pack data v1\x00"

KIND_ROLLUP = "rollup"
KIND_ROLLUP_NAMES = "rollup-names"
KIND_ROLLUP_V2 = "rollup_v2"
KIND_RECORD = "rec"
KIND_NOTIFY = "notify"
KIND_TELEMETRY = "telemetry"
KINDS = frozenset({KIND_ROLLUP, KIND_ROLLUP_NAMES, KIND_ROLLUP_V2, KIND_RECORD, KIND_NOTIFY, KIND_TELEMETRY})


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def body_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()


def signed_bytes(kind: str, origin: str, key: str, stamp: Any, h: str) -> bytes:
    return DATA_PREFIX + _canonical({"h": h, "k": kind, "key": key, "o": origin, "s": stamp}).encode("ascii")


def sign(kind: str, key: str, stamp: Any, h: str, signing: Signing) -> Signature:
    return Signature(signing.install_id, signing.key().sign(signed_bytes(kind, signing.install_id, key, stamp, h)))


def verify(kind: str, origin: str, key: str, stamp: Any, h: str, sig: Optional[Signature], lst: Any) -> bool:
    if not capabilities.mesh_on() or not isinstance(lst, RosterV2) or sig is None or kind not in KINDS or sig.signer != origin:
        return False
    entry = lst.entry(origin)
    if entry is None:
        return False
    return verify_bytes(signed_bytes(kind, origin, key, stamp, h), sig, entry.fed_public_key)


def kid(public_key: str) -> str:
    return hashlib.sha256(public_key.encode("ascii", "replace")).hexdigest()[:16]


def own_kid(signing: Signing) -> Optional[str]:
    key = signing.public_key_for(signing.install_id)
    return kid(key) if key else None


def try_sign(kind: str, key: str, stamp: Any, h: str, signing: Signing) -> Optional[Signature]:
    try:
        return sign(kind, key, stamp, h, signing)
    except DeviceKeyUnavailable:
        return None
