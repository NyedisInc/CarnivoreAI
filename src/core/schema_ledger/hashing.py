
from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import re
import textwrap
import types
from typing import Any, Callable, Dict, List, Optional, Set

_CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RUNG_HELPER_NAME = re.compile(r"^_?v\d+_")
_MAX_DEPTH = 6
_OWN_CODE_PREFIX = "src."


def sql_rung_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def normalized_source(source: str) -> str:
    lines = []
    for line in textwrap.dedent(source).splitlines():
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _referenced_names(tree: ast.AST) -> List[Any]:
    found: List[Any] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            found.append((node.value.id, node.attr))
        elif isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.extend(("import", node.module, alias.name) for alias in node.names)
    return found


def _is_rung_specific(obj: Any) -> bool:
    if not isinstance(obj, types.FunctionType) or not obj.__module__.startswith(_OWN_CODE_PREFIX):
        return False
    return "ddl" in obj.__module__ or bool(_RUNG_HELPER_NAME.match(obj.__name__))


def _resolve(ref: Any, namespace: Dict[str, Any]) -> Optional[Any]:
    if isinstance(ref, str):
        return namespace.get(ref)
    if ref[0] == "import":
        try:
            return getattr(importlib.import_module(ref[1]), ref[2], None)
        except ImportError:
            return None
    base = namespace.get(ref[0])
    return getattr(base, ref[1], None) if isinstance(base, types.ModuleType) else None


def _collect(func: Callable[..., Any], depth: int, seen: Set[int], parts: Dict[str, str]) -> None:
    if id(func) in seen or depth > _MAX_DEPTH:
        return
    seen.add(id(func))
    source = inspect.getsource(func)
    parts[f"{func.__module__}.{func.__qualname__}"] = normalized_source(source)
    namespace = getattr(func, "__globals__", {})
    for ref in _unique(_referenced_names(ast.parse(textwrap.dedent(source)))):
        obj = _resolve(ref, namespace)
        label = ref if isinstance(ref, str) else ".".join(ref[2:] if ref[0] == "import" else ref)
        text = _constant_text(obj) if _CONSTANT_NAME.match(label.split(".")[-1]) else None
        if text is not None:
            parts[f"{func.__module__}:{label}"] = text
        elif _is_rung_specific(obj):
            _collect(obj, depth + 1, seen, parts)


def _constant_text(obj: Any) -> Optional[str]:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (tuple, list, frozenset)) and obj and all(isinstance(x, str) for x in obj):
        return "\n;;\n".join(sorted(obj) if isinstance(obj, frozenset) else obj)
    return None


def _unique(refs: List[Any]) -> List[Any]:
    out: List[Any] = []
    for ref in refs:
        if ref not in out:
            out.append(ref)
    return out


def step_rung_hash(step: Callable[..., Any]) -> str:
    parts: Dict[str, str] = {}
    _collect(step, 0, set(), parts)
    digest = hashlib.sha256()
    for key in sorted(parts):
        digest.update(f"{key}\n{parts[key]}\n--\n".encode("utf-8"))
    return digest.hexdigest()
