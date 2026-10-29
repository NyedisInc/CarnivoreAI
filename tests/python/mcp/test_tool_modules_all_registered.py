
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterator, Tuple

import pytest

import src.core.mcp as mcp_pkg
from src.core.mcp import tools


def _modules() -> Iterator[Tuple[str, object]]:
    for info in pkgutil.iter_modules(mcp_pkg.__path__):
        if info.name.endswith("_tools"):
            yield info.name, importlib.import_module(f"src.core.mcp.{info.name}")


@pytest.mark.parametrize("name,module", list(_modules()), ids=lambda v: v if isinstance(v, str) else "")
def test_declared_writes_are_registered_and_in_the_write_union(name: str, module: object) -> None:
    writes = frozenset(getattr(module, "WRITE_TOOLS", ()) or ())
    reads = frozenset(getattr(module, "READ_TOOLS", ()) or ())
    missing_from_registry = {t for t in writes | reads if t not in tools._TOOLS}
    assert not missing_from_registry, f"{name}: declared but not registered in _TOOLS: {sorted(missing_from_registry)}"
    missing_write = writes - tools.WRITE_TOOLS
    assert not missing_write, f"{name}: declared WRITE_TOOLS missing from tools.WRITE_TOOLS (a read token could call them): {sorted(missing_write)}"
    assert not (writes & reads), f"{name}: in both READ_TOOLS and WRITE_TOOLS: {sorted(writes & reads)}"


def test_no_registered_read_tool_is_also_classified_write() -> None:
    reads = set()
    for _name, module in _modules():
        reads |= set(getattr(module, "READ_TOOLS", ()) or ())
    assert not (reads & tools.WRITE_TOOLS), sorted(reads & tools.WRITE_TOOLS)
