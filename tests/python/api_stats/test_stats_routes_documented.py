"""Every stats route handler carries a docstring and a return annotation (API-10)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[3] / "src" / "api"
MODULES = ("stats_routes.py", "stats_maintenance_routes.py")


def undocumented(source: str) -> list[str]:
    """Names of decorated route handlers lacking a docstring or a return annotation.

    Inputs: source (str). Output: list[str].
    """
    return [
        n.name for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.decorator_list
        and any("router" in ast.unparse(d) for d in n.decorator_list)
        and (not ast.get_docstring(n) or n.returns is None)
    ]


@pytest.mark.parametrize("module", MODULES)
def test_every_handler_is_documented_and_typed(module: str) -> None:
    assert undocumented((API / module).read_text(encoding="utf-8")) == []


def test_the_check_goes_red_on_a_bare_handler() -> None:
    assert undocumented("@router.get('/x')\nasync def h():\n    return 1\n") == ["h"]
