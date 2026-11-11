
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

ENGINES_KEY = "engines"
CARNIVORE_ENGINE = "carnivore"
_VERSION = re.compile(r"^(0|[1-9]\d*)(?:\.(0|[1-9]\d*)){0,2}$")
_COMPARATOR = re.compile(r"^(>=|<=|<|>|=|\^|~)?(.+)$")
_OPERATORS = frozenset({">=", "<=", "<", ">", "=", "^", "~"})
_LOWER_OPS = frozenset({">=", "=", "", "^", "~"})
_UPPER_OPS = frozenset({"<", "<="})
_IMPLIED_UPPER = frozenset({"^", "~", "=", ""})
_HYPHEN = " - "
_OR = "||"
_PARTS = 3

Version = Tuple[int, int, int]


class EngineRangeError(ValueError):
    pass


@dataclass(frozen=True)
class EngineRange:

    lower: Version
    has_upper: bool

    @property
    def lower_text(self) -> str:
        return ".".join(str(p) for p in self.lower)


def _version(text: str, raw: str) -> Version:
    if not _VERSION.match(text):
        raise EngineRangeError(f"engines.carnivore {raw!r}: {text!r} is not a version (write numbers like 1.16.6, no wildcards or tags)")
    parts = [int(p) for p in text.split(".")] + [0] * _PARTS
    return parts[0], parts[1], parts[2]


def _comparators(text: str) -> List[str]:
    tokens = text.split()
    out: List[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] in _OPERATORS and i + 1 < len(tokens) and tokens[i + 1][:1].isdigit():
            out.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def _set_bounds(text: str, raw: str) -> Tuple[Optional[Version], bool]:
    if _HYPHEN in text:
        left, _, right = text.partition(_HYPHEN)
        _version(right.strip(), raw)
        return _version(left.strip(), raw), True
    lowers: List[Version] = []
    upper = False
    for token in _comparators(text):
        op, body = _COMPARATOR.match(token).groups()
        op = op or ""
        version = _version(body, raw)
        if op == ">":
            raise EngineRangeError(f"engines.carnivore {raw!r}: write >= with the first version you support; > cannot become a minimum version")
        if op in _LOWER_OPS:
            lowers.append(version)
        upper = upper or op in _UPPER_OPS or op in _IMPLIED_UPPER
    return (max(lowers) if lowers else None), upper


def parse_range(raw: object) -> EngineRange:
    if not isinstance(raw, str) or not raw.strip():
        raise EngineRangeError("engines.carnivore must be a version range such as \">=1.16.6\"")
    lowers: List[Version] = []
    upper = False
    for part in raw.split(_OR):
        if not part.strip():
            raise EngineRangeError(f"engines.carnivore {raw!r}: an empty alternative around ||")
        lower, has_upper = _set_bounds(part.strip(), raw)
        if lower is None:
            raise EngineRangeError(f"engines.carnivore {raw!r}: every alternative needs a lower bound (>=, =, ^ or ~ with a version)")
        lowers.append(lower)
        upper = upper or has_upper
    return EngineRange(min(lowers), upper)


def engines_range(authored: dict) -> Optional[EngineRange]:
    if ENGINES_KEY not in authored:
        return None
    engines = authored[ENGINES_KEY]
    if not isinstance(engines, dict) or set(engines) != {CARNIVORE_ENGINE}:
        raise EngineRangeError("engines must be an object with exactly one key, carnivore, holding a version range")
    return parse_range(engines[CARNIVORE_ENGINE])
