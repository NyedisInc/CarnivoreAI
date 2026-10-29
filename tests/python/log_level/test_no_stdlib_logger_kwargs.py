from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
STDLIB_KWARGS = {"exc_info", "extra", "stack_info", "stacklevel"}


def _is_get_logger(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getLogger"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logging"
    )


def _target_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def offenders(source: str) -> list[int]:
    tree = ast.parse(source)
    loggers = {
        key
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _is_get_logger(node.value)
        for key in (_target_key(t) for t in node.targets)
        if key
    }
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in LEVELS or _target_key(node.func.value) not in loggers:
            continue
        if any(k.arg is None or k.arg not in STDLIB_KWARGS for k in node.keywords):
            bad.append(node.lineno)
    return bad


def test_checker_goes_red_on_a_fixture() -> None:
    bad = "import logging\nlogger = logging.getLogger(__name__)\nlogger.debug('x', session=1)\n"
    attr = "import logging\nclass A:\n    def __init__(self):\n        self._l = logging.getLogger('a')\n    def f(self):\n        self._l.error('x', error='e')\n"
    fine = "import logging\nlogger = logging.getLogger('a')\nlogger.info('x %s', 1, exc_info=True, extra={'a': 1})\n"
    assert offenders(bad) == [3]
    assert offenders(attr) == [6]
    assert offenders(fine) == []


def test_src_has_no_stdlib_logger_called_with_keywords() -> None:
    found = {
        f"{path.relative_to(SRC.parent)}:{line}"
        for path in SRC.rglob("*.py")
        for line in offenders(path.read_text(encoding="utf-8"))
    }
    assert not found, f"use structlog.get_logger() for keyword logging: {sorted(found)}"
