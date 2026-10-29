
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Optional

import structlog

from .log_safe import log_value
from .minisign import MinisignFormatError, parse_public_key, parse_signature, verify
from .trust_root import TrustRoot

logger = structlog.get_logger(__name__)

FIRST_LINE = "carnivore-publisher-key-revoked-v1"

STATEMENT_LINES = 4

MAX_STATEMENT_BYTES = 1024

MAX_SINCE_CHARS = 64

_KEY_ID_RE = re.compile(r"[0-9A-F]{16}")
_PUB_LINE_RE = re.compile(r"[A-Za-z0-9+/]{56}")


@dataclass(frozen=True)
class PublisherKeyRevocation:

    revoked_key_id: str
    replacement_pub: str
    since: str


def render_statement(*, revoked_key_id: str, replacement_pub: str, since: str) -> bytes:
    if not _KEY_ID_RE.fullmatch(revoked_key_id):
        raise ValueError("revoked_key_id must be 16 uppercase hex")
    if not _PUB_LINE_RE.fullmatch(replacement_pub):
        raise ValueError("replacement_pub must be one 56 character base64 line")
    try:
        replacement = parse_public_key(replacement_pub)
    except MinisignFormatError as exc:
        raise ValueError(f"replacement_pub is not a public key: {exc}") from exc
    if replacement.key_id == revoked_key_id:
        raise ValueError("a key cannot replace itself")
    if not since or len(since) > MAX_SINCE_CHARS or "\n" in since or "\r" in since:
        raise ValueError(f"since must be one line of 1 to {MAX_SINCE_CHARS} characters")
    lines = (FIRST_LINE, revoked_key_id, replacement_pub, since)
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _parse_statement(statement: bytes) -> PublisherKeyRevocation:
    text = statement.decode("utf-8")
    if not text.endswith("\n"):
        raise ValueError("statement does not end with a line feed")
    lines = text[:-1].split("\n")
    if len(lines) != STATEMENT_LINES:
        raise ValueError(f"statement has {len(lines)} lines, expected {STATEMENT_LINES}")
    if lines[0] != FIRST_LINE:
        raise ValueError("statement header is not " + FIRST_LINE)
    parsed = PublisherKeyRevocation(
        revoked_key_id=lines[1], replacement_pub=lines[2], since=lines[3],
    )
    render_statement(
        revoked_key_id=parsed.revoked_key_id,
        replacement_pub=parsed.replacement_pub,
        since=parsed.since,
    )
    return parsed


def _ignore(reason: str, **context: str) -> None:
    logger.warning(
        "catalog_publisher_key_revocation_ignored",
        reason=reason,
        **{k: log_value(v) for k, v in context.items()},
    )


def verify_publisher_key_revocation(
    statement: bytes, minisig_text: str, trust_root: TrustRoot,
) -> Optional[PublisherKeyRevocation]:
    spare = trust_root.spare_publisher_key
    live = trust_root.publisher_key
    if spare is None or live is None:
        _ignore("no spare publisher key is pinned, so no revocation can be accepted")
        return None
    if len(statement) > MAX_STATEMENT_BYTES:
        _ignore("statement is larger than any real one")
        return None
    try:
        signature = parse_signature(minisig_text)
    except MinisignFormatError as exc:
        _ignore(f"signature is malformed: {exc}")
        return None
    if signature.key_id == live.key_id:
        _ignore(
            "signed by the current publisher key, which can never retire itself",
            signature_key_id=signature.key_id,
        )
        return None
    if signature.key_id != spare.key_id:
        _ignore(
            "signed by a key that is not the pinned spare publisher key",
            signature_key_id=signature.key_id,
        )
        return None
    if not signature.prehashed:
        _ignore("signature uses the legacy algorithm, not the prehashed one")
        return None
    try:
        ok = verify(statement, signature, spare, expect_prehashed=True)
    except MinisignFormatError as exc:
        _ignore(f"signature could not be checked: {exc}")
        return None
    if not ok:
        _ignore("signature does not verify under the pinned spare")
        return None
    try:
        parsed = _parse_statement(statement)
    except ValueError as exc:
        _ignore(f"statement is malformed: {exc}")
        return None
    if parsed.revoked_key_id != live.key_id:
        _ignore(
            "names a key that is not the current publisher key",
            named_key_id=parsed.revoked_key_id,
        )
        return None
    if parse_public_key(parsed.replacement_pub).key_id == spare.key_id:
        _ignore("replacement is the spare itself")
        return None
    return parsed


def apply_publisher_revocation(
    trust_root: TrustRoot, revocation: Optional[PublisherKeyRevocation],
) -> TrustRoot:
    live = trust_root.publisher_key
    if revocation is None or live is None or revocation.revoked_key_id != live.key_id:
        return trust_root
    return dataclasses.replace(
        trust_root,
        publisher_key=parse_public_key(revocation.replacement_pub),
        spare_publisher_key=None,
    )
