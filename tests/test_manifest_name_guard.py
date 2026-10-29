
from __future__ import annotations

import ast
import pathlib

from tests.helpers.guard_fold import assert_no_offenders

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
SCAN_ROOTS = (SRC / "core" / "skills", SRC / "api")
ALLOWED_FILE = "kinds.py"
LITERAL = "SKILL.md"


def _docstring_node_ids(tree: ast.AST) -> set:
    node_ids = set()
    scopes = [tree] + [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for scope in scopes:
        body = getattr(scope, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node_ids.add(id(first.value))
    return node_ids


def _hardcoded_literal_lines(path: pathlib.Path) -> list:
    tree = ast.parse(path.read_text(), filename=str(path))
    docstring_ids = _docstring_node_ids(tree)
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value == LITERAL
            and id(node) not in docstring_ids
        ):
            lines.append(node.lineno)
    return lines


def _scan_targets() -> list:
    targets = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path.name == ALLOWED_FILE:
                continue
            targets.append(path)
    return targets


def test_no_hardcoded_skill_manifest_name():
    def check(path: pathlib.Path) -> None:
        bad_lines = _hardcoded_literal_lines(path)
        assert not bad_lines, (
            f"hardcodes {LITERAL!r} in code at line(s) "
            f"{', '.join(str(n) for n in bad_lines)}. The manifest name for a "
            "kind belongs in src/core/skills/kinds.py (MANIFEST_FOR / "
            "manifest_name), never as a literal at a call site - that is the "
            "exact shape that produced a crash once and a consent bypass once "
            "when a second and third catalog kind arrived."
        )

    assert_no_offenders("no hardcoded skill manifest name", _scan_targets(),
                        check, label=lambda p: str(p.relative_to(SRC)))


def test_the_check_can_actually_fail(tmp_path):
    decoy = tmp_path / "decoy.py"
    decoy.write_text('MANIFEST_NAME = "SKILL.md"\n')
    assert _hardcoded_literal_lines(decoy) == [1]
