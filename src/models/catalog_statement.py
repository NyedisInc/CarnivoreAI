
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .catalog import PUBLISHER_RE, SKILL_NAME_RE, VERSION_RE, _match_or_raise

RELEASE_STATEMENT_HEADER = "carnivore-release-v1"


def release_statement(
    *,
    kind: str,
    publisher: str,
    name: str,
    version: str,
    repo: str,
    path: str,
    commit: str,
    digest: str,
) -> bytes:
    fields = {
        "kind": kind,
        "publisher": publisher,
        "name": name,
        "version": version,
        "repo": repo,
        "path": path,
        "commit": commit,
        "digest": digest,
    }
    for field_name, value in fields.items():
        if not value:
            raise ValueError(f"release statement field {field_name} is empty")
        if "\n" in value or "\r" in value:
            raise ValueError(
                f"release statement field {field_name} contains a line break"
            )
    _match_or_raise(fields["publisher"], PUBLISHER_RE, "publisher")
    _match_or_raise(fields["name"], SKILL_NAME_RE, "name")
    _match_or_raise(fields["version"], VERSION_RE, "version")

    lines = [RELEASE_STATEMENT_HEADER, *fields.values()]
    return ("".join(f"{line}\n" for line in lines)).encode("utf-8")


DELEGATION_STATEMENT_HEADER = "carnivore-publisher-key-v1"

ANY_HANDLE = "*"

CUSTODIES = ("self", "catalog", "first_party", "kms")

KMS_HANDLES = ("carnivore", "external")

_KEY_ID_RE = re.compile(r"^[0-9A-F]{16}$")
_PUB_LINE_RE = re.compile(r"^[A-Za-z0-9+/]{1,200}={0,2}$")


@dataclass(frozen=True)
class PublisherKeyStatement:

    handle: str
    key_id: str
    pub: str
    custody: str
    added: str


def publisher_key_statement(
    *, handle: str, key_id: str, pub: str, custody: str, added: str,
) -> bytes:
    fields = {
        "handle": handle, "key_id": key_id, "pub": pub,
        "custody": custody, "added": added,
    }
    for name, value in fields.items():
        if not value or "\n" in value or "\r" in value:
            raise ValueError(f"publisher key statement field {name} is empty or has a line break")
    if handle != ANY_HANDLE:
        _match_or_raise(handle, PUBLISHER_RE, "delegated handle")
    if custody not in CUSTODIES:
        raise ValueError(f"publisher key statement custody must be one of {CUSTODIES}")
    if handle == ANY_HANDLE and custody != "catalog":
        raise ValueError("a * delegation needs custody catalog")
    if custody == "kms" and handle not in KMS_HANDLES:
        raise ValueError(f"a kms delegation must name one of {KMS_HANDLES}")
    if not _KEY_ID_RE.match(key_id):
        raise ValueError("publisher key statement key_id is not 16 uppercase hex")
    if not _PUB_LINE_RE.match(pub):
        raise ValueError("publisher key statement pub is not a base64 line")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", added):
        raise ValueError("publisher key statement added is not YYYY-MM-DD")
    date.fromisoformat(added)
    lines = [DELEGATION_STATEMENT_HEADER, *fields.values()]
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def parse_publisher_key_statement(text: str) -> PublisherKeyStatement:
    lines = text.split("\n")
    if len(lines) != 7 or lines[6] != "" or lines[0] != DELEGATION_STATEMENT_HEADER:
        raise ValueError("not a carnivore-publisher-key-v1 statement")
    handle, key_id, pub, custody, added = lines[1:6]
    if publisher_key_statement(
        handle=handle, key_id=key_id, pub=pub, custody=custody, added=added,
    ) != text.encode("utf-8"):
        raise ValueError("statement is not in canonical form")
    return PublisherKeyStatement(handle, key_id, pub, custody, added)
