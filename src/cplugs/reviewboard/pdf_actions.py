
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Set

from src.cplugs.reviewboard import office_text as limits
from src.cplugs.reviewboard.pdf_doc import Parsed
from src.cplugs.reviewboard.pdf_lexer import Meter
from src.cplugs.reviewboard.pdf_objects import Dict as PdfDict, Name, Ref
from src.cplugs.reviewboard.pdf_streams import REASON_DUP_KEY, PdfUnreadable

OPEN_TIME_TYPES = {"URI": "OpenURI", "GoToR": "OpenGoToR", "GoToE": "OpenGoToE"}
MAX_VISITS = 1_000_000
_TICK = 4096
ACTION_KEYS = {"S", "URI", "F", "Next", "JS", "D"}
DOCUMENT_KEYS = {"OpenAction", "AA"}


def _values(root: Any) -> Iterator[Any]:
    stack = [root]
    while stack:
        item = stack.pop()
        yield item
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _roots(parsed: Parsed, meter: Meter) -> List[Any]:
    roots, seen = [], 0
    everything: List[Any] = [v for versions in parsed.objects.values() for v in versions] + parsed.loose
    for top in everything:
        for item in _values(top):
            seen += 1
            if seen % _TICK == 0:
                meter.deadline.check()
            if isinstance(item, dict):
                if isinstance(item, PdfDict) and item.dups & (DOCUMENT_KEYS | (ACTION_KEYS if "S" in item else set())):
                    raise PdfUnreadable(REASON_DUP_KEY)
                if "OpenAction" in item:
                    roots.append(("open", item["OpenAction"]))
                if "AA" in item:
                    roots.append(("aa", item["AA"]))
    return roots


def _resolve(value: Any, objects: Dict[int, List[Any]]) -> List[Any]:
    return objects.get(value.num, []) if isinstance(value, Ref) else [value]


def open_time_features(parsed: Parsed, meter: Meter) -> Set[str]:
    found: Set[str] = set()
    todo: List[Any] = []
    for kind, value in _roots(parsed, meter):
        for item in _resolve(value, parsed.objects):
            if kind == "aa" and isinstance(item, dict):
                todo.extend(v for v in item.values())
            else:
                todo.append(item)
    visited: Set[int] = set()
    visits = 0
    while todo:
        visits += 1
        if visits > MAX_VISITS:
            raise PdfUnreadable(limits.REASON_TOO_BIG)
        if visits % _TICK == 0:
            meter.deadline.check()
        item = todo.pop()
        for version in _resolve(item, parsed.objects):
            if id(version) in visited:
                continue
            visited.add(id(version))
            if isinstance(version, PdfDict):
                kind = version.get("S")
                if isinstance(kind, Name) and str(kind) in OPEN_TIME_TYPES:
                    found.add(OPEN_TIME_TYPES[str(kind)])
                if "URI" in version:
                    found.add(OPEN_TIME_TYPES["URI"])
                if "S" in version or "URI" in version:
                    todo.append(version.get("Next"))
            elif isinstance(version, list):
                todo.extend(version)
    return found
