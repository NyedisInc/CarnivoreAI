
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Optional

import structlog

from .log_safe import log_value
from .minisign import MinisignFormatError, parse_signature, verify
from .trust_root import TrustRoot

logger = structlog.get_logger(__name__)

INDEX_KEY_REVOKED_HEADER = "carnivore-index-key-revoked-v1"

STATEMENT_LINES = 5

_FIRST_SERIAL_RE = re.compile(r"[1-9][0-9]{0,15}")

MAX_STATEMENT_BYTES = 1024

MAX_SINCE_CHARS = 64

_KEY_ID_RE = re.compile(r"[0-9A-F]{16}")


@dataclass(frozen=True)
class IndexKeyRevocation:

    revoked_key_id: str
    successor_key_id: str
    first_serial: int
    since: str


FIRST_SERIAL_UNRECORDED = 0


def render_statement(
    *, revoked_key_id: str, successor_key_id: str, first_serial: int, since: str,
) -> bytes:
    for name, value in (("revoked_key_id", revoked_key_id),
                        ("successor_key_id", successor_key_id)):
        if not _KEY_ID_RE.fullmatch(value):
            raise ValueError(f"{name} must be 16 uppercase hex")
    if revoked_key_id == successor_key_id:
        raise ValueError("a key cannot succeed itself")
    if isinstance(first_serial, bool) or not isinstance(first_serial, int):
        raise ValueError("first_serial must be an integer")
    if not _FIRST_SERIAL_RE.fullmatch(str(first_serial)):
        raise ValueError("first_serial must be 1 to 16 digits, 1 or more")
    if not since or len(since) > MAX_SINCE_CHARS:
        raise ValueError(f"since must be 1 to {MAX_SINCE_CHARS} characters")
    if "\n" in since or "\r" in since:
        raise ValueError("since contains a line break")
    lines = (
        INDEX_KEY_REVOKED_HEADER, revoked_key_id, successor_key_id,
        str(first_serial), since,
    )
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _parse_statement(statement: bytes) -> IndexKeyRevocation:
    text = statement.decode("utf-8")
    if not text.endswith("\n"):
        raise ValueError("statement does not end with a line feed")
    lines = text[:-1].split("\n")
    if len(lines) != STATEMENT_LINES:
        raise ValueError(f"statement has {len(lines)} lines, expected {STATEMENT_LINES}")
    if lines[0] != INDEX_KEY_REVOKED_HEADER:
        raise ValueError("statement header is not " + INDEX_KEY_REVOKED_HEADER)
    if not _FIRST_SERIAL_RE.fullmatch(lines[3]):
        raise ValueError("first serial is not canonical decimal")
    parsed = IndexKeyRevocation(
        revoked_key_id=lines[1], successor_key_id=lines[2],
        first_serial=int(lines[3]), since=lines[4],
    )
    render_statement(
        revoked_key_id=parsed.revoked_key_id,
        successor_key_id=parsed.successor_key_id,
        first_serial=parsed.first_serial,
        since=parsed.since,
    )
    return parsed


def _ignore(reason: str, **context: str) -> None:
    logger.warning(
        "catalog_index_key_revocation_ignored",
        reason=reason,
        **{k: log_value(v) for k, v in context.items()},
    )


def verify_index_key_revocation(
    statement: bytes, minisig_text: str, trust_root: TrustRoot,
) -> Optional[IndexKeyRevocation]:
    spare = trust_root.spare_index_key
    live = trust_root.index_key
    if spare is None or live is None:
        _ignore("no spare index key is pinned, so no revocation can be accepted")
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
            "signed by the current index key, which can never retire itself",
            signature_key_id=signature.key_id,
        )
        return None
    if signature.key_id != spare.key_id:
        _ignore(
            "signed by a key that is not the pinned spare",
            signature_key_id=signature.key_id,
            spare_key_id=spare.key_id,
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
    except (UnicodeDecodeError, ValueError) as exc:
        _ignore(f"statement is malformed: {exc}")
        return None

    if parsed.revoked_key_id != live.key_id:
        _ignore(
            "names a key that is not the current index key",
            named_key_id=parsed.revoked_key_id,
            live_key_id=live.key_id,
        )
        return None
    if parsed.successor_key_id != spare.key_id:
        _ignore(
            "names a successor that is not the pinned spare",
            successor_key_id=parsed.successor_key_id,
        )
        return None
    return parsed


def active_trust_root(
    trust_root: TrustRoot, revocation: Optional[IndexKeyRevocation],
) -> TrustRoot:
    if revocation is None:
        return trust_root
    live, spare = trust_root.index_key, trust_root.spare_index_key
    if live is None or revocation.revoked_key_id != live.key_id:
        return trust_root
    if spare is not None and revocation.successor_key_id == spare.key_id:
        floor = revocation.first_serial
        if floor == FIRST_SERIAL_UNRECORDED:
            logger.error(
                "catalog_index_key_first_serial_unrecorded",
                revoked_key_id=revocation.revoked_key_id,
                consequence="the spare's floor is the pinned minimum serial",
            )
            floor = trust_root.min_index_serial
        return dataclasses.replace(
            trust_root, index_key=spare, spare_index_key=None,
            min_index_serial=floor,
        )
    logger.error(
        "catalog_index_key_revoked_without_successor",
        revoked_key_id=revocation.revoked_key_id,
        successor_key_id=log_value(revocation.successor_key_id),
        consequence="every index is refused until an app release pins a new key",
    )
    return dataclasses.replace(trust_root, index_key=None, spare_index_key=None)
