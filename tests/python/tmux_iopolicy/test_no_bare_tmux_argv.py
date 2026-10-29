
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"

def _is_bare(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value == "tmux" or (node.value.startswith("/") and node.value.endswith("/tmux")))


def _has_flag(rest: List[ast.AST]) -> bool:
    return any(isinstance(n, ast.Constant) and n.value in ("-L", "-S", "-V", "-f") for n in rest)


def bare_tmux_argvs(source: str) -> List[int]:
    hits: List[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and _is_bare(node.elts[0]) and _has_flag(node.elts[1:]):
            hits.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args and _is_bare(node.args[0]) and _has_flag(node.args[1:]):
            hits.append(node.lineno)
    return sorted(set(hits))


def _scan() -> Tuple[List[str], int]:
    findings: List[str] = []
    count = 0
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        count += 1
        for line in bare_tmux_argvs(path.read_text(encoding="utf-8")):
            findings.append(f"{rel}:{line}")
    return findings, count


def test_the_scan_can_go_red() -> None:
    assert bare_tmux_argvs('x = ["tmux", "-L", s]') == [1]
    assert bare_tmux_argvs('await asyncio.create_subprocess_exec(\n    "tmux", "-L", s)') == [1]
    assert bare_tmux_argvs('run(("/opt/homebrew/bin/tmux", "-L", s))') == [1]
    assert bare_tmux_argvs('x = tmux_argv_prefix(s) + ["list-sessions"]') == []
    assert bare_tmux_argvs('x = Info(backend="tmux")') == []
    assert bare_tmux_argvs('x = ("tmux", "tmux")') == []


def test_no_bare_tmux_argv_in_src() -> None:
    findings, count = _scan()
    assert count > 500, f"scanned only {count} files; the scan looked at nothing"
    assert not findings, (
        "a bare tmux argv skips the version-matching picker; use tmux_argv_prefix(socket) from "
        "src/core/tmux_discovery.py:\n" + "\n".join(findings))
