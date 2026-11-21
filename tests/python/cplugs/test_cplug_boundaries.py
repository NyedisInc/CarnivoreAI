
from __future__ import annotations

import sys
from typing import List

from tests.python.cplugs.sections import CPLUGS, CPLUGS_PACKAGE, ROOT, SDK_PACKAGE, feature_ids, imported_modules
from tests.python.cplugs.test_cplug_sections import feature_core_known

THIRD_PARTY = {"fastapi", "pydantic", "structlog", "backports", "compression", "uvicorn"}


def violations(source: str, cplug_id: str) -> List[str]:
    known = feature_core_known(cplug_id)
    own = f"{CPLUGS_PACKAGE}.{cplug_id}"
    bad = []
    for name in imported_modules(source, known):
        top = name.split(".")[0]
        ok = (name == "__future__" or top in sys.stdlib_module_names or top in THIRD_PARTY
              or name == SDK_PACKAGE or name.startswith(f"{SDK_PACKAGE}.")
              or name == own or name.startswith(f"{own}.")
              or name in known)
        if not ok:
            bad.append(name)
    return bad


def test_every_cplug_imports_only_the_sdk_and_itself():
    shipped = ["argent", "crate", "devwidgetlab", "flow", "huddle", "reviewboard", "save", "sessionchat", "share", "timemachine", "tmdevtools", "unread"]
    assert feature_ids() == [i for i in shipped if (ROOT / "src" / "plugins" / i).is_dir()]
    found = {}
    for cplug_id in feature_ids():
        for path in (CPLUGS / cplug_id).rglob("*.py"):
            bad = violations(path.read_text(), cplug_id)
            if bad:
                found[str(path.relative_to(ROOT))] = bad
    assert found == {}


def test_the_boundary_check_can_fail():
    assert violations("from src.core.mcp import tools\nimport src.api.auth\nfrom src.plugins.other import x\n", "huddle") == [
        "src.core.mcp", "src.api.auth", "src.plugins.other"]
    assert violations("import json\nfrom fastapi import Depends\nfrom src.plugins.sdk import ToolSpec\nfrom . import rules\n", "huddle") == []
    assert violations("from src.core.deepsearch import fallback_hook\n", "save") == []
    assert violations("from src.core.deepsearch import index_scope\n", "save") == ["src.core.deepsearch"]
    assert violations("from src.core.deepsearch.fallback_hook import register\n", "save") == []
    assert violations("from src.core.deepsearch.fallback_hook import register\n", "huddle") == ["src.core.deepsearch.fallback_hook"]


def core_importers(text: str, ids: List[str]) -> bool:
    return any(f"{CPLUGS_PACKAGE}.{i}" in text or f"from {CPLUGS_PACKAGE} import {i}" in text for i in ids)


def test_core_never_imports_an_cplug_except_the_ship_list():
    ids = feature_ids()
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT / "src")
        if rel.parts[0] == "plugins" and (len(rel.parts) == 2 or rel.parts[1] in ids):
            continue
        if core_importers(path.read_text(), ids):
            offenders.append(str(rel))
    assert offenders == []
    assert core_importers("from src.plugins.huddle import store\n", ["huddle"])
