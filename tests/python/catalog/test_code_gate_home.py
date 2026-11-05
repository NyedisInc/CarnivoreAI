
from __future__ import annotations

import ast
from pathlib import Path

from src.api import catalog_consent
from src.core.skills import code_gate

CORE_SKILLS = Path(code_gate.__file__).parent
GATE = "staged_plugin_declares_code"


def test_gate_is_defined_in_core() -> None:
    assert code_gate.staged_plugin_declares_code.__module__ == "src.core.skills.code_gate"
    assert code_gate.staged_plugin_declares_code("mod", CORE_SKILLS) is True


def test_api_consent_module_does_not_define_gate() -> None:
    tree = ast.parse(Path(catalog_consent.__file__).read_text())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert GATE not in defined


def test_core_skills_do_not_import_gate_from_api() -> None:
    offenders = []
    for path in CORE_SKILLS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src.api"):
                if any(a.name == GATE for a in node.names):
                    offenders.append(path.name)
    assert offenders == []
