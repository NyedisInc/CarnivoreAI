"""Judging a fetched catalog index: is it signed, is it current, whose is it.

THIS FUNCTION IS PURE, AND THAT IS A SECURITY PROPERTY RATHER THAN A
STYLE ONE. Every input is an argument: the bytes, the signature, the
trust root, the revocations already seen, the last serial verified, the
current time, and the one serial the user has re-consented to. That last
one is the clearest case of the rule: a consent is a NUMBER passed in for
one call, never a mode this module can be left switched into. There is no
file read, no network call, no environment
lookup and no wall clock anywhere in this module or in its item level
companion. A verifier that reached for any of those would have a branch a
test could not steer, and the branch a test cannot steer is the branch
that has never been proven able to refuse anything.
``tests/test_catalog_verify.py`` asserts the absence of a clock by
reading this file's own source.

THE ORDER OF THE CHECKS IS THE DESIGN.

  1. NO PINNED KEY MEANS NO INDEX. An unpinned client that accepted an
     index would be trusting whoever served it. This refuses first, as
     ``signature_invalid``, and it is the state a checkout ships in
     today because an agent never holds a private key.
  2. SIGNATURE BEFORE PARSE. The bytes are verified before a single one
     of them reaches pydantic. A parser is an attack surface, and handing
     unverified input to one is how a fetched document becomes something
     far worse than a bad catalog. The signature must also be PREHASHED:
     minisign will happily verify a legacy signature, and accepting one
     would let a signer downgrade the construction the catalog committed
     to.
  3. Only then the envelope, the serial, freshness, the revocations, and
     the items.

ONE BAD ITEM COSTS ONE ITEM. The envelope is parsed with ``items`` left
as raw values and each one is judged on its own in
:mod:`src.core.catalog.verify_items`. The whole index is refused only
when the envelope itself is unusable.

STALENESS IS A BADGE, ROLLBACK IS A REFUSAL. An index that is merely old
is still the index the publisher signed: the user is told "as of" and can
still install. An index whose serial went BACKWARDS is an attacker
replaying a correctly signed older document to hide a fix, and no amount
of valid signature makes that acceptable.

NOTHING HERE LOGS KEY MATERIAL, A SIGNATURE, OR THE INDEX BODY. Key ids,
serials, counts, item ids and refusal reasons are logged. A digest is
logged on a mismatch, because a digest is a public number and the
mismatch is undebuggable without it.
"""

from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta
from typing import Any, List, Optional, Set, Union

import structlog
from pydantic import ValidationError

from src.models.catalog import DIGEST_RE, CatalogItem, ItemVersion

from .delegation import verify_delegations
from .minisign import MinisignFormatError, PublicKey, Signature, parse_signature, verify
from .revocation import KIND_KEY, KIND_VERSION, verify_revocations
from .trust_root import TrustRoot
from .verify_items import (
    duplicate_id_verdict,
    errors_summary,
    report_key_impersonation,
    verify_item,
)
from .verify_types import (
    DIGEST_MISMATCH,
    INDEX_NOT_JSON,
    INDEX_ROLLBACK,
    INDEX_SERIAL_JUMP,
    SCRIPTS_NOT_SUPPORTED,
    SIGNATURE_INVALID,
    IndexEnvelope,
    ItemRefusal,
    VerifiedIndex,
    VerifyRefusal,
)

logger = structlog.get_logger(__name__)


def _refuse(code: str, detail: str, **context: Any) -> VerifyRefusal:
    logger.warning("catalog_index_refused", code=code, detail=detail, **context)
    return VerifyRefusal(code=code, detail=detail)


def _verify_signature(
    index_bytes: bytes, minisig_text: str, index_key: PublicKey,
) -> Union[VerifyRefusal, Signature]:
    """Check the detached index signature, before anything parses the body.

    Description: four refusals, all of them ``signature_invalid``, each
      with a distinct detail so a log says which one happened.

      1. The ``.minisig`` did not parse at all.
      2. It names a key that is not the pinned index key. This is checked
         here as well as inside
         :func:`~src.core.catalog.minisign.verify` so the refusal can SAY
         which key signed, instead of reporting the arithmetic failure
         that would follow.
      3. It is a LEGACY (raw message) signature. The catalog commits to
         the prehashed construction, and accepting the other one would
         let a signer choose the weaker framing. Like the key id above,
         this is ALSO bound inside
         :func:`~src.core.catalog.minisign.verify`, which is passed
         ``expect_prehashed=True``; it is refused here first only so the
         detail can SAY the algorithm was wrong rather than reporting
         the arithmetic failure that would follow.
      4. The mathematics disagreed, over the message or over the trusted
         comment.
    Inputs: index_bytes (bytes) - the body exactly as fetched.
      minisig_text (str) - the detached signature file. index_key
      (PublicKey) - the PINNED index key.
    Output: the parsed Signature, or a VerifyRefusal.
    Example: _verify_signature(body, sig_text, pinned).prehashed -> True
    """
    try:
        signature = parse_signature(minisig_text)
    except MinisignFormatError as exc:
        return _refuse(SIGNATURE_INVALID, f"index signature is malformed: {exc}")

    if signature.key_id != index_key.key_id:
        return _refuse(
            SIGNATURE_INVALID,
            "index is signed by a key that is not the pinned index key",
            signature_key_id=signature.key_id,
            pinned_key_id=index_key.key_id,
        )

    if not signature.prehashed:
        return _refuse(
            SIGNATURE_INVALID,
            "index signature uses the legacy algorithm, not the prehashed one",
            key_id=signature.key_id,
        )

    try:
        ok = verify(
            index_bytes, signature, index_key, expect_prehashed=True,
        )
    except MinisignFormatError as exc:
        return _refuse(
            SIGNATURE_INVALID, f"index signature could not be checked: {exc}"
        )
    if not ok:
        return _refuse(
            SIGNATURE_INVALID,
            "index signature does not verify under the pinned index key",
            key_id=index_key.key_id,
        )
    return signature


def _parse_envelope(index_bytes: bytes) -> Union[VerifyRefusal, IndexEnvelope]:
    try:
        payload = json.loads(index_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        return _refuse(INDEX_NOT_JSON, "index body is not valid utf-8")
    except json.JSONDecodeError as exc:
        return _refuse(INDEX_NOT_JSON, f"index body is not valid json: {exc.msg}")
    except RecursionError:
        return _refuse(INDEX_NOT_JSON, "index body nests deeper than json can parse")

    if not isinstance(payload, dict):
        return _refuse(INDEX_NOT_JSON, "index body is not a json object")

    try:
        return IndexEnvelope.model_validate(payload)
    except ValidationError as exc:
        return _refuse(
            INDEX_NOT_JSON, f"index envelope is invalid: {errors_summary(exc)}"
        )


def _check_serial(
    serial: int,
    trust_root: TrustRoot,
    last_verified_serial: int,
    consented_serial: Optional[int],
) -> Optional[VerifyRefusal]:
    floor = max(trust_root.min_index_serial, last_verified_serial)
    if serial < floor:
        return _refuse(
            INDEX_ROLLBACK,
            f"index serial {serial} is below the floor {floor}",
            serial=serial,
            floor=floor,
        )
    if consented_serial is not None and serial == consented_serial:
        return None
    if serial - floor > trust_root.max_serial_jump:
        return _refuse(
            INDEX_SERIAL_JUMP,
            f"index serial jumped from {floor} to {serial}",
            serial=serial,
            floor=floor,
            max_serial_jump=trust_root.max_serial_jump,
        )
    return None


def _parse_generated_at(text: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed


def verify_index(
    index_bytes: bytes,
    minisig_text: str,
    *,
    trust_root: TrustRoot,
    seen_revocations: frozenset,
    last_verified_serial: int,
    now: datetime,
    consented_serial: Optional[int] = None,
) -> Union[VerifiedIndex, VerifyRefusal]:
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("verify_index requires a timezone aware 'now'")

    if trust_root.index_key is None:
        logger.warning(
            "catalog_trust_root_unpinned",
            missing_keys=["index"],
            consequence="every index is refused as signature_invalid",
        )
        return _refuse(
            SIGNATURE_INVALID,
            "no index key is pinned, so no index can be verified",
        )

    signature = _verify_signature(index_bytes, minisig_text, trust_root.index_key)
    if isinstance(signature, VerifyRefusal):
        return signature

    envelope = _parse_envelope(index_bytes)
    if isinstance(envelope, VerifyRefusal):
        return envelope

    serial_refusal = _check_serial(
        envelope.serial, trust_root, last_verified_serial, consented_serial
    )
    if serial_refusal is not None:
        return serial_refusal

    generated_at = _parse_generated_at(envelope.generated_at)
    if generated_at is None:
        return _refuse(
            INDEX_NOT_JSON,
            "generated_at is not an iso 8601 timestamp with a timezone offset",
        )
    degraded = now - generated_at > timedelta(days=trust_root.staleness_days)

    delegations = verify_delegations(envelope.publishers, trust_root.publisher_key)
    verified_revocations, ignored_revocations = verify_revocations(
        envelope.revocations, trust_root.publisher_key, delegations
    )
    effective = frozenset(seen_revocations) | frozenset(verified_revocations)
    revoked_key_ids = {
        ref.subject.strip().upper() for ref in effective if ref.kind == KIND_KEY
    }
    revoked_versions = {
        ref.subject for ref in effective if ref.kind == KIND_VERSION
    }
    report_key_impersonation(envelope.publishers, trust_root.publisher_key)

    items: List[CatalogItem] = []
    untrusted: List[CatalogItem] = []
    refused: List[ItemRefusal] = []
    claimed_ids: Set[str] = set()
    for raw_item in envelope.items:
        verdict = verify_item(
            raw_item,
            publisher_key=trust_root.publisher_key,
            revoked_key_ids=revoked_key_ids,
            revoked_versions=revoked_versions,
            delegations=delegations,
        )
        if verdict.item is not None:
            if verdict.item.id in claimed_ids:
                verdict = duplicate_id_verdict(verdict.item.id)
            else:
                claimed_ids.add(verdict.item.id)
        if verdict.refusal is not None:
            refused.append(verdict.refusal)
        elif verdict.item is not None and verdict.trusted:
            items.append(verdict.item)
        elif verdict.item is not None:
            untrusted.append(verdict.item)

    logger.info(
        "catalog_index_verified",
        serial=envelope.serial,
        index_key_id=trust_root.index_key.key_id,
        items=len(items),
        untrusted_items=len(untrusted),
        refused_items=len(refused),
        revocations=len(verified_revocations),
        ignored_revocations=ignored_revocations,
        degraded=degraded,
    )
    return VerifiedIndex(
        serial=envelope.serial,
        generated_at=generated_at,
        degraded=degraded,
        items=tuple(items),
        untrusted_items=tuple(untrusted),
        refused=tuple(refused),
        revocations=tuple(verified_revocations),
        index_key_id=trust_root.index_key.key_id,
        featured=tuple(envelope.featured),
    )


def check_digest(expected_hex: str, actual_hex: str) -> Optional[VerifyRefusal]:
    expected = expected_hex.strip()
    actual = actual_hex.strip()
    if not DIGEST_RE.fullmatch(expected) or not DIGEST_RE.fullmatch(actual):
        return _refuse(DIGEST_MISMATCH, "malformed digest")
    if hmac.compare_digest(expected, actual):
        return None
    return _refuse(
        DIGEST_MISMATCH,
        f"expected digest {expected} but the staged bytes hash to {actual}",
    )


def check_scripts(version: ItemVersion) -> Optional[VerifyRefusal]:
    if version.scripts > 0:
        return _refuse(
            SCRIPTS_NOT_SUPPORTED,
            f"version carries {version.scripts} script members",
            scripts=version.scripts,
        )
    return None
