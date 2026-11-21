from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterator, Tuple

BARE_RAISE_NAMES = frozenset({"ValueError", "RuntimeError"})
VALIDATOR_MARKS = ("validator",)
VALIDATOR_FUNCTIONS = frozenset({"__post_init__"})
SHIM_KEYWORDS = frozenset({"app", "state"})
API_LAYER = "src/api"


def _py_files(root: Path, sub: str = "src") -> Iterator[Tuple[str, Path]]:
    for path in sorted((root / sub).rglob("*.py")):
        yield path.relative_to(root).as_posix(), path


def _parse(path: Path) -> ast.AST:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return ast.parse("")


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_validator(fn: ast.AST) -> bool:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if fn.name in VALIDATOR_FUNCTIONS:
        return True
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if any(mark in _name_of(target) for mark in VALIDATOR_MARKS):
            return True
    return False


def _bare_raises(node: ast.AST, in_validator: bool = False) -> int:
    total = 0
    for child in ast.iter_child_nodes(node):
        inside = in_validator or _is_validator(child)
        if isinstance(child, ast.Raise) and not inside and child.exc is not None:
            exc = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
            if isinstance(exc, ast.Name) and exc.id in BARE_RAISE_NAMES:
                total += 1
        total += _bare_raises(child, inside)
    return total


def bare_raise_counts(root: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rel, path in _py_files(root):
        found = _bare_raises(_parse(path))
        if found:
            counts[rel] = found
    return counts


def _is_shim(call: ast.Call) -> bool:
    name = _name_of(call.func)
    if name == "AppRequest":
        return True
    return name == "SimpleNamespace" and any(kw.arg in SHIM_KEYWORDS for kw in call.keywords)


def _shim_roots(tree: ast.AST) -> int:
    shims = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_shim(n)]
    inner = {id(d) for s in shims for d in ast.walk(s) if d is not s and isinstance(d, ast.Call) and _is_shim(d)}
    return sum(1 for s in shims if id(s) not in inner)


def request_shim_counts(root: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rel, path in _py_files(root):
        if rel.startswith(API_LAYER + "/"):
            continue
        found = _shim_roots(_parse(path))
        if found:
            counts[rel] = found
    return counts


def over_baseline(actual: Dict[str, int], baseline: Dict[str, int]) -> Dict[str, Tuple[int, int]]:
    return {p: (baseline.get(p, 0), n) for p, n in actual.items() if n > baseline.get(p, 0)}


def stale_baseline(actual: Dict[str, int], baseline: Dict[str, int]) -> Dict[str, Tuple[int, int]]:
    return {p: (n, actual.get(p, 0)) for p, n in baseline.items() if actual.get(p, 0) < n}
