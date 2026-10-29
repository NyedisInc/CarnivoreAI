
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set

EXCEPTION_NAMES = frozenset({"e", "exc", "err", "error", "ex", "exception"})


SAFE_ATTRS = frozenset({"code", "codes", "status", "status_code"})


def _mentions(node: ast.AST, names: Set[str]) -> bool:
    safe = {id(a.value) for a in ast.walk(node) if isinstance(a, ast.Attribute) and a.attr in SAFE_ATTRS}
    return any(isinstance(n, ast.Name) and n.id in names and id(n) not in safe for n in ast.walk(node))


def _http_exceptions(scope: ast.AST) -> Iterator[ast.Call]:
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "HTTPException":
            yield node


def _detail_of(call: ast.Call) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == "detail":
            return keyword.value
    return call.args[1] if len(call.args) > 1 else None


def raw_detail_lines(source: str) -> List[int]:
    tree = ast.parse(source)
    hits: Set[int] = set()
    for node in ast.walk(tree):
        names: Set[str] = set()
        scopes: List[ast.AST] = []
        if isinstance(node, ast.ExceptHandler) and node.name:
            names, scopes = {node.name}, list(node.body)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {a.arg for a in node.args.args + node.args.kwonlyargs} & EXCEPTION_NAMES
            scopes = list(node.body)
        for scope in scopes:
            for call in _http_exceptions(scope):
                detail = _detail_of(call)
                if names and detail is not None and _mentions(detail, names):
                    hits.add(call.lineno)
    return sorted(hits)


def scan_tree(root: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        found = raw_detail_lines(path.read_text(encoding="utf-8"))
        if found:
            counts[path.relative_to(root).as_posix()] = len(found)
    return counts


SOFT_FIELDS = frozenset({"detail", "message", "reason", "warning", "note", "layout_detail"})
_LOG_CALLS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log", "log_failure",
                        "api_error", "soft_failure", "refusal_error", "HTTPException", "bind"})


def _carries_text(node: ast.AST, names: Set[str]) -> bool:
    if isinstance(node, ast.Call) and _call_name(node) in _LOG_CALLS:
        return False
    attr_bases = {id(a.value) for a in ast.walk(node) if isinstance(a, ast.Attribute)}
    return any(isinstance(n, ast.Name) and n.id in names and id(n) not in attr_bases for n in ast.walk(node))


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "id", getattr(call.func, "attr", ""))


def soft_leak_lines(source: str) -> List[int]:
    hits: Set[int] = set()
    for handler in ast.walk(ast.parse(source)):
        if not (isinstance(handler, ast.ExceptHandler) and handler.name):
            continue
        names = {handler.name}
        for node in (n for stmt in handler.body for n in ast.walk(stmt)):
            if isinstance(node, ast.Call) and _call_name(node) not in _LOG_CALLS:
                hits.update(k.value.lineno for k in node.keywords
                            if k.arg in SOFT_FIELDS and _carries_text(k.value, names))
            elif isinstance(node, ast.Assign) and _carries_text(node.value, names):
                hits.update(node.lineno for t in node.targets
                            if isinstance(t, ast.Name) and any(f in t.id for f in SOFT_FIELDS))
    return sorted(hits)


def scan_soft(root: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        found = soft_leak_lines(path.read_text(encoding="utf-8"))
        if found:
            counts[path.relative_to(root).as_posix()] = len(found)
    return counts


SOFT_KNOWN_PATH = Path(__file__).with_name("raw_detail_soft_known.json")


KNOWN_PATH = Path(__file__).with_name("raw_detail_known.json")
API_ROOT = Path(__file__).resolve().parents[3] / "src" / "api"


if __name__ == "__main__":
    import json
    import sys

    found = scan_tree(API_ROOT)
    soft = scan_soft(API_ROOT)
    if "--write" in sys.argv:
        KNOWN_PATH.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        SOFT_KNOWN_PATH.write_text(json.dumps(soft, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(sum(found.values()), "raw-detail sites in", len(found), "files;", sum(soft.values()), "in a 200 body field")
