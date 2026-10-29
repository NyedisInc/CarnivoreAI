
from __future__ import annotations

import ast
import builtins
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import importlib

from tests.helpers.guard_fold import assert_no_offenders

def _route_modules() -> list[str]:
    found = []
    for path in sorted((ROOT / "src" / "api").glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text()
        if "= APIRouter(" not in text:
            continue
        found.append(f"src.api.{path.stem}")
    return found


ROUTE_MODULES = _route_modules()

assert len(ROUTE_MODULES) >= 20, ROUTE_MODULES


def _locally_bound(fn: ast.AST) -> set:
    bound = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                bound.add(arg.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    bound.add(item.optional_vars.id)
        elif isinstance(node, ast.Lambda):
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                bound.add(arg.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
        elif isinstance(node, ast.comprehension):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
    return bound


def _check_handler_names(module_name: str) -> None:
    routes = importlib.import_module(module_name)
    tree = ast.parse(Path(routes.__file__).read_text())
    module_names = set(vars(routes)) | set(dir(builtins))
    offenders = []

    def walk(node, enclosing):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visible = enclosing | _locally_bound(node)
            for child in node.body:
                walk(child, visible)
            for inner in ast.walk(node):
                if not (isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load)):
                    continue
                if inner.id in visible or inner.id in module_names:
                    continue
                offenders.append(f"{node.name}:{inner.lineno} -> {inner.id}")
            return
        for child in ast.iter_child_nodes(node):
            walk(child, enclosing)

    walk(tree, set())

    assert not offenders, (
        "route handlers reference names that resolve nowhere; each is a "
        "NameError and a bare 500 the first time it is called: "
        f"{sorted(set(offenders))[:10]}"
    )


def test_every_route_handler_resolves_its_helper_names():
    assert_no_offenders("route handler names resolve", ROUTE_MODULES,
                        _check_handler_names)


def test_run_in_threadpool_is_available_at_module_scope():
    def check(module_name: str) -> None:
        routes = importlib.import_module(module_name)
        if "run_in_threadpool" not in Path(routes.__file__).read_text():
            return
        assert hasattr(routes, "run_in_threadpool"), (
            "run_in_threadpool is not at module scope; a handler that uses "
            "it without its own local import will NameError at call time"
        )

    assert_no_offenders("run_in_threadpool at module scope", ROUTE_MODULES, check)
