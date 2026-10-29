
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

PACKAGE = Path(__file__).resolve().parents[3] / "src" / "core" / "crate_format"
TEMPLATE = PACKAGE / "templates" / "extract.py"
ALLOWED_TOP = ("src.core.blobcodec", "src.core.crate_format")
LAZY_ONLY = ("src.core.crate_crypto",)


def _modules(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return ["." if node.level else (node.module or "")]
    return []


def _stdlib(name: str) -> bool:
    return name.split(".")[0] in sys.stdlib_module_names or name in ("__future__", "compression", "compression.zstd")


def _under(name: str, prefixes) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def violations(source: str, stdlib_only: bool = False) -> List[str]:
    tree = ast.parse(source)
    bad: List[str] = []
    for node in ast.walk(tree):
        for name in _modules(node):
            if _stdlib(name) or name == ".":
                continue
            top = node in tree.body
            if stdlib_only:
                bad.append(name)
            elif _under(name, ALLOWED_TOP):
                continue
            elif _under(name, LAZY_ONLY) and not top:
                continue
            else:
                bad.append(name)
    return bad


def test_package_imports_respect_the_boundary() -> None:
    sources = [p for p in PACKAGE.rglob("*.py") if p != TEMPLATE]
    assert len(sources) >= 14
    found = {str(p.relative_to(PACKAGE)): violations(p.read_text()) for p in sources}
    assert {k: v for k, v in found.items() if v} == {}


def test_crypto_is_only_imported_lazily_somewhere() -> None:
    reader = (PACKAGE / "reader.py").read_text()
    assert "src.core.crate_crypto" in reader and violations(reader) == []


def test_template_extract_is_stdlib_only() -> None:
    assert violations(TEMPLATE.read_text(), stdlib_only=True) == []


def test_red_control_flags_a_top_level_third_party_import() -> None:
    bad = "import cryptography\nfrom src.core.crate_crypto.age import AgeReader\nfrom src.api import x\n"
    assert violations(bad) == ["cryptography", "src.core.crate_crypto.age", "src.api"]
    assert violations("def f():\n    from src.core.crate_crypto import age\n") == []
    assert violations("def f():\n    import fastapi\n") == ["fastapi"]
    assert violations("from src.core.blobcodec import codec\n", stdlib_only=True) == ["src.core.blobcodec"]
