
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MUTATING_VERBS = frozenset({"post", "put", "patch", "delete"})

_DECORATOR = re.compile(r"@(\w+)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']*)[\"']")
_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)", re.M)
_PREFIX = re.compile(r"(\w+)\s*=\s*APIRouter\([^)]*prefix\s*=\s*[\"']([^\"']*)[\"']", re.S)


@dataclass(frozen=True)
class Route:

    method: str
    path: str
    handler: str
    where: str

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def find_routes(src_root: Path, repo_root: Path) -> list[Route]:
    routes: list[Route] = []
    for path in src_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(errors="replace")
        prefixes = {m.group(1): m.group(2) for m in _PREFIX.finditer(text)}
        for m in _DECORATOR.finditer(text):
            router, verb, sub = m.groups()
            found = _DEF.search(text, m.end())
            if not found:
                continue
            handler = found.group(1)
            full = prefixes.get(router, "") + sub
            if not full:
                continue
            line = text[: m.start()].count("\n") + 1
            routes.append(Route(verb.upper(), full, handler, f"{path.relative_to(repo_root)}:{line}"))
    return sorted(routes, key=lambda r: r.key)


_WORD = re.compile(r"\w+")
_SLASH_PATH = re.compile(r"(?:/[\w.{}-]+)+")


@dataclass(frozen=True)
class TestIndex:

    words: frozenset[str]
    pairs: frozenset[tuple[str, str]]
    singles: frozenset[str]
    files: tuple[tuple[frozenset[str], frozenset[str]], ...] = ()


def build_test_index(tests_root: Path, exclude: Iterable[Path] = ()) -> TestIndex:
    skip = [p.resolve() for p in exclude]
    words: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    singles: set[str] = set()
    per_file: list[tuple[frozenset[str], frozenset[str]]] = []
    for p in tests_root.rglob("*.py"):
        resolved = p.resolve()
        if "__pycache__" in p.parts or any(resolved == s or s in resolved.parents for s in skip):
            continue
        text = p.read_text(errors="replace")
        file_words = frozenset(_WORD.findall(text))
        file_segs: set[str] = set()
        words.update(file_words)
        for hit in _SLASH_PATH.findall(text):
            segs = [x for x in hit.split("/") if x]
            file_segs.update(segs)
            pairs.update(zip(segs, segs[1:]))
        singles.update(file_segs)
        per_file.append((file_words, frozenset(file_segs)))
    return TestIndex(frozenset(words), frozenset(pairs), frozenset(singles), tuple(per_file))


def is_named(route: Route, index: TestIndex) -> bool:
    if route.handler in index.words:
        return True
    segs = [s for s in route.path.split("/") if s]
    if len(segs) < 2:
        return bool(segs) and (segs[0] in index.singles)
    a, b = segs[-2], segs[-1]
    if _named_by_prefix_and_tail(segs, index) or _named_by_prefix_and_verb(route, segs, index):
        return True
    a_any, b_any = a.startswith("{"), b.startswith("{")
    if a_any and b_any:
        return bool(index.pairs)
    if a_any:
        return any(second == b for _, second in index.pairs)
    if b_any:
        return any(first == a for first, _ in index.pairs)
    return (a, b) in index.pairs


def _named_by_prefix_and_tail(segs: list[str], index: TestIndex) -> bool:
    static = [x for x in segs if not x.startswith("{")]
    if len(static) < 2 or segs[-1].startswith("{"):
        return False
    first, last = static[0], segs[-1]
    return any(first in w and last in g for w, g in index.files)


def _named_by_prefix_and_verb(route: Route, segs: list[str], index: TestIndex) -> bool:
    if not segs[-1].startswith("{"):
        return False
    module = route.where.split(":")[0].rsplit("/", 1)[-1].removesuffix(".py")
    verb = route.method.lower()
    static = [x for x in segs if not x.startswith("{")]
    return any(verb in w and (module in w or all(x in g for x in static)) for w, g in index.files)


def untested_routes(src_root: Path, tests_root: Path, repo_root: Path, exclude: Iterable[Path] = ()) -> list[Route]:
    index = build_test_index(tests_root, exclude)
    return [r for r in find_routes(src_root, repo_root) if not is_named(r, index)]
