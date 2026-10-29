
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[3]
CPLUGS = ROOT / "src" / "cplugs"
HOST_DIRS = {"sdk", "host", "runtime", "sdk_py"}
THIRD_PARTY = {"fastapi", "pydantic", "structlog", "backports", "compression"}
CORE_EXTENSION_POINTS = {"save": {"src.core.deepsearch.fallback_hook"}, "crate": {"src.core.deepsearch.fallback_hook"},
                         "flow": {"src.core.flow_data.collect.build", "src.core.flow_data.collect.participants", "src.core.flow_data.collect.transcript",
                          "src.core.flow_data.feed", "src.core.flow_data.live", "src.core.flow_data.tail"}}


def cplug_ids() -> List[str]:
    return sorted(p.name for p in CPLUGS.iterdir() if p.is_dir() and p.name not in HOST_DIRS and (p / "__init__.py").exists())


def violations(source: str, cplug_id: str) -> List[str]:
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            names = [node.module or ""]
            declared = [f"{node.module}.{a.name}" for a in node.names]
            if all(d in CORE_EXTENSION_POINTS.get(cplug_id, ()) for d in declared):
                names = declared
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            ok = (name == "__future__" or top in sys.stdlib_module_names or top in THIRD_PARTY
                  or name == "src.cplugs.sdk" or name.startswith("src.cplugs.sdk.")
                  or name == f"src.cplugs.{cplug_id}" or name.startswith(f"src.cplugs.{cplug_id}.")
                  or name in CORE_EXTENSION_POINTS.get(cplug_id, ()))
            if not ok:
                bad.append(name)
    return bad


def test_every_cplug_imports_only_the_sdk_and_itself():
    assert cplug_ids() == ["crate", "devwidgetlab", "flow", "huddle", "publicboard", "reviewboard", "save", "share", "timemachine", "tmdevtools", "unread"]
    found = {}
    for cplug_id in cplug_ids():
        for path in (CPLUGS / cplug_id).rglob("*.py"):
            bad = violations(path.read_text(), cplug_id)
            if bad:
                found[str(path.relative_to(ROOT))] = bad
    assert found == {}


def test_the_boundary_check_can_fail():
    assert violations("from src.core.mcp import tools\nimport src.api.auth\nfrom src.cplugs.other import x\n", "huddle") == [
        "src.core.mcp", "src.api.auth", "src.cplugs.other"]
    assert violations("import json\nfrom fastapi import Depends\nfrom src.cplugs.sdk import ToolSpec\nfrom . import rules\n", "huddle") == []
    assert violations("from src.core.deepsearch import fallback_hook\n", "save") == []
    assert violations("from src.core.deepsearch import index_scope\n", "save") == ["src.core.deepsearch"]
    assert violations("from src.core.deepsearch.fallback_hook import register\n", "save") == []
    assert violations("from src.core.deepsearch.fallback_hook import register\n", "huddle") == ["src.core.deepsearch.fallback_hook"]


def core_importers(text: str, ids: List[str]) -> bool:
    return any(f"src.cplugs.{i}" in text or f"from src.cplugs import {i}" in text for i in ids)


def test_core_never_imports_an_cplug_except_the_ship_list():
    ids = cplug_ids()
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT / "src")
        if rel.parts[0] == "cplugs" and (len(rel.parts) == 2 or rel.parts[1] in ids):
            continue
        if core_importers(path.read_text(), ids):
            offenders.append(str(rel))
    assert offenders == []
    assert core_importers("from src.cplugs.huddle import store\n", ["huddle"])
