
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("src", "scripts")
HELPER = Path("src/core/safe_io/readonly_db.py")
NEEDLE = "mode=ro"
EXEMPT = {
    Path("src/core/db_steps.py"): "frozen schema rung",
    Path("src/cplugs/huddle/cli/move_files_to_root.py"): "huddle plugin, out of scope",
    Path("scripts/release/public/gates/live.py"): "standalone release gate",
}


def _code_strings_with_needle(tree: ast.AST) -> list[int]:
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and NEEDLE in n.value and id(n) not in docstrings
    ]


def find_offenders(root: Path) -> list[str]:
    found = []
    for d in SCAN_DIRS:
        for f in (root / d).rglob("*.py"):
            rel = f.relative_to(root)
            if rel == HELPER or rel in EXEMPT:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            found += [f"{rel}:{ln}" for ln in _code_strings_with_needle(tree)]
    return found


def test_no_handwritten_readonly_uri() -> None:
    assert find_offenders(REPO) == []


def test_guard_goes_red_on_a_fixture(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text('import sqlite3\nsqlite3.connect(f"file:{p}?mode=ro", uri=True)\n')
    (tmp_path / "src" / "ok.py").write_text('"""opened mode=ro"""\n')
    assert find_offenders(tmp_path) == ["src/bad.py:2"]
