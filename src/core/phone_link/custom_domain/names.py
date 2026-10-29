
from __future__ import annotations

import functools
import ipaddress
import re
from pathlib import Path
from typing import FrozenSet, Tuple

import idna

OUR_ZONE = "carnivore.ai"
MAX_LENGTH = 253
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_SPECIAL_USE = frozenset({"local", "localhost", "internal", "arpa", "onion", "test", "example", "invalid"})
_PSL_PATH = Path(__file__).with_name("public_suffix.txt")


class BadDomain(ValueError):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@functools.lru_cache(maxsize=1)
def _rules() -> Tuple[FrozenSet[str], FrozenSet[str], FrozenSet[str]]:
    plain, wild, exc = set(), set(), set()
    for line in _PSL_PATH.read_text(encoding="ascii").split():
        if line.startswith("!"):
            exc.add(line[1:])
        elif line.startswith("*."):
            wild.add(line[2:])
        else:
            plain.add(line)
    return frozenset(plain), frozenset(wild), frozenset(exc)


def public_suffix_labels(labels: Tuple[str, ...]) -> int:
    plain, wild, exc = _rules()
    best = 1
    for i in range(len(labels)):
        suffix = ".".join(labels[i:])
        count = len(labels) - i
        if suffix in exc:
            return count - 1
        if suffix in plain or (i + 1 < len(labels) and ".".join(labels[i + 1:]) in wild):
            best = max(best, count)
    return best


def _under(name: str, zone: str) -> bool:
    return name == zone or name.endswith("." + zone)


def normalise(raw: str) -> str:
    name = raw.strip().lower()
    if name.endswith("."):
        name = name[:-1]
    if not name or len(name) > MAX_LENGTH:
        raise BadDomain("length")
    if "*" in name:
        raise BadDomain("wildcard")
    try:
        name = idna.encode(name, uts46=True).decode("ascii")
    except (idna.IDNAError, UnicodeError):
        raise BadDomain("idna") from None
    labels = tuple(name.split("."))
    try:
        ipaddress.ip_address(name)
        raise BadDomain("ip_literal")
    except ValueError:
        pass
    if labels[-1].isdigit():
        raise BadDomain("ip_literal")
    if len(name) > MAX_LENGTH or any(len(l) > 63 or not _LABEL.match(l) for l in labels):
        raise BadDomain("label")
    if _under(name, OUR_ZONE):
        raise BadDomain("our_zone")
    if labels[-1] in _SPECIAL_USE or _under(name, "home.arpa"):
        raise BadDomain("special_use")
    suffix = public_suffix_labels(labels)
    if suffix >= len(labels):
        raise BadDomain("public_suffix")
    if suffix + 1 == len(labels):
        raise BadDomain("apex")
    return name


def display(domain: str) -> str:
    try:
        return idna.decode(domain)
    except (idna.IDNAError, UnicodeError):
        return domain
