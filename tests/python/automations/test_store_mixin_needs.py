
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

import src.config  # noqa: F401
from src.core.automations.store import AutomationStore

_AUTOMATIONS = Path(__file__).resolve().parents[3] / "src" / "core" / "automations"
_HOST_FILE = _AUTOMATIONS / "store_host.py"
_MIXIN_FILES = [_AUTOMATIONS / "store_claim.py"]
_PROTOCOL = "StoreCore"


def declared_host_names() -> Set[str]:
    if not _HOST_FILE.exists():
        return set()
    for node in ast.parse(_HOST_FILE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == _PROTOCOL:
            names: Set[str] = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.add(item.target.id)
            return names
    return set()


def _annotation_text(arg: ast.arg) -> str:
    return ast.unparse(arg.annotation) if arg.annotation is not None else ""


def mixin_problems(source: str, declared: Set[str]) -> List[str]:
    problems: List[str] = []
    for cls in (n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name.endswith("Mixin")):
        own = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for method in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            used = {a.attr for a in ast.walk(method) if isinstance(a, ast.Attribute)
                    and isinstance(a.value, ast.Name) and a.value.id == "self"}
            needs = used - own
            for name in sorted(needs - declared):
                problems.append(f"{cls.name}.{method.name} uses self.{name}, which {_PROTOCOL} does not declare")
            if needs and _PROTOCOL not in _annotation_text(method.args.args[0]):
                problems.append(f"{cls.name}.{method.name} uses the host but does not annotate self: {_PROTOCOL}")
    return problems


FIXTURE_UNDECLARED = '''
class SpareMixin:
    def go(self: StoreCore):
        return self._write() and self.some_new_host_attr
'''
FIXTURE_UNANNOTATED = '''
class SpareMixin:
    def go(self):
        return self._write()
'''


def test_the_shipped_mixins_use_only_declared_host_attributes() -> None:
    declared = declared_host_names()
    problems = [p for f in _MIXIN_FILES for p in mixin_problems(f.read_text(encoding="utf-8"), declared)]
    assert not problems, "\n".join(problems)


def test_the_host_provides_everything_the_protocol_declares() -> None:
    declared = declared_host_names()
    assert declared, f"{_PROTOCOL} declares nothing"
    set_in_init = set(AutomationStore.__init__.__code__.co_names)
    missing = sorted(n for n in declared if not hasattr(AutomationStore, n) and n not in set_in_init)
    assert not missing, f"AutomationStore lacks {missing}"


def test_the_checker_goes_red_on_an_undeclared_attribute() -> None:
    found = mixin_problems(FIXTURE_UNDECLARED, {"_write"})
    assert any("some_new_host_attr" in p for p in found), found


def test_the_checker_goes_red_on_an_unannotated_self() -> None:
    found = mixin_problems(FIXTURE_UNANNOTATED, {"_write"})
    assert any("does not annotate self" in p for p in found), found
