
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from src.core.catalog.revocation import version_subject
from src.core.catalog.verify_items import _verify_release
from src.core.catalog.verify_types import DIGEST_MISMATCH, KEY_UNTRUSTED, SIGNATURE_INVALID, VERSION_REVOKED

NOT_PINNED = "not_pinned"
KEY_REVOKED = "key_revoked"
VERSION_REVOKED = "version_revoked"
SIGNATURE_FAILED = "signature_failed"
DIGEST_DIFFERS = "digest_differs"

INSTALL_ROUTE_CODES = {
    NOT_PINNED: KEY_UNTRUSTED,
    KEY_REVOKED: KEY_UNTRUSTED,
    VERSION_REVOKED: VERSION_REVOKED,
    SIGNATURE_FAILED: SIGNATURE_INVALID,
    DIGEST_DIFFERS: DIGEST_MISMATCH,
}


def vouch(
    item: Any,
    version: Any,
    digest: str,
    revoked: tuple,
    *,
    publisher_key: Any,
    pinned_key_id: Optional[str],
    verify: Callable[..., Any] = _verify_release,
    extra_subjects: Iterable[str] = (),
) -> Optional[str]:
    if pinned_key_id is None or publisher_key is None or version.sig.key_id.strip().upper() != pinned_key_id:
        return NOT_PINNED
    if version.digest != digest:
        return DIGEST_DIFFERS
    revoked_keys, revoked_versions = revoked
    if pinned_key_id in revoked_keys:
        return KEY_REVOKED
    if version_subject(item.id, version.v) in revoked_versions or any(s in revoked_versions for s in extra_subjects):
        return VERSION_REVOKED
    return SIGNATURE_FAILED if verify(item, version, publisher_key) is not None else None
