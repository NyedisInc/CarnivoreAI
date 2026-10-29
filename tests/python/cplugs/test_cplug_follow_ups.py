
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Set

import pytest

from src.cplugs.host import runtime
from src.cplugs.sdk.definition import CplugDefinition
from tests.helpers.catalog_text import catalog_text, slice_paths

ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = {d.id: d for d in runtime.definitions()}
KEY_REF = re.compile(r"""['"`](cplug\.([a-z0-9]+)\.[A-Za-z0-9_.\-]*)""")
SOURCE_SUFFIXES = (".py", ".ts", ".svelte", ".js")
DEFINED_KEY = re.compile(r"""['"](cplug\.[a-z0-9]+\.[^'"]*)['"]\s*:""")


def served(definition: CplugDefinition) -> Set[str]:
    if definition.router is None:
        return set()
    prefix = definition.router.prefix
    return {r.path[len(prefix):] or "/" for r in definition.router.routes if hasattr(r, "path")}


def missing_routes(declared: List[str], available: Set[str]) -> List[str]:
    return sorted(p for p in declared if p not in available)


@pytest.mark.parametrize("pid", sorted(DEFINITIONS))
def test_every_declared_route_exists(pid: str) -> None:
    definition = DEFINITIONS[pid]
    declared = list(definition.manifest.owns.routes)
    assert missing_routes(declared, served(definition)) == [], f"{pid}: owns.routes names a route its router does not serve"


UNDECLARED_ROUTES_OK = {
    "huddle": "no sidecar yet: the Task Manager split owner adds it (#1711), 62 routes",
    "devwidgetlab": "being edited in #1944 (widget contract); it declares /capture and /status there",
}


def undeclared_routes(declared: List[str], available: Set[str]) -> List[str]:
    return sorted(p for p in available if p not in declared)


@pytest.mark.parametrize("pid", sorted(DEFINITIONS))
def test_every_served_route_is_declared(pid: str) -> None:
    if pid in UNDECLARED_ROUTES_OK:
        pytest.skip(UNDECLARED_ROUTES_OK[pid])
    definition = DEFINITIONS[pid]
    assert undeclared_routes(list(definition.manifest.owns.routes), served(definition)) == [], f"{pid}: serves a route owns.routes does not declare"


def test_the_served_route_check_can_fail() -> None:
    assert undeclared_routes(["/a"], {"/a", "/b"}) == ["/b"]
    assert undeclared_routes([], served(DEFINITIONS["flow"])) == ["/feed", "/run"]
    assert set(UNDECLARED_ROUTES_OK) <= set(DEFINITIONS)


def test_the_declared_route_check_can_fail() -> None:
    assert missing_routes(["/a", "/ghost"], {"/a", "/b"}) == ["/ghost"]
    assert served(DEFINITIONS["save"]) >= {"/summary", "/settings"}


def test_a_plugin_that_declares_routes_has_a_router() -> None:
    for pid, definition in DEFINITIONS.items():
        if definition.manifest.owns.routes:
            assert definition.router is not None and definition.manifest.surfaces.routes, pid


def registry_rows(pid: str) -> Set[str]:
    path = ROOT / "web" / "src" / "cplugs" / pid / "style-guide.json"
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8"))["files"])


@pytest.mark.parametrize("pid", sorted(DEFINITIONS))
def test_every_registry_row_is_declared_and_every_declared_specimen_has_a_row(pid: str) -> None:
    declared = set(DEFINITIONS[pid].manifest.owns.style_guide)
    rows = registry_rows(pid)
    if not rows and not declared:
        pytest.skip("no style guide specimens")
    assert rows - declared == set(), f"{pid}: registry rows the manifest does not declare in owns.style_guide"
    assert declared - rows == set(), f"{pid}: owns.style_guide names a file with no registry row"


def test_the_registry_row_check_can_fail() -> None:
    assert {"a.svelte", "b.svelte"} - {"a.svelte"} == {"b.svelte"}
    assert registry_rows("save"), "save keeps its rows in its own folder: the check reads real data"


def own_key_violations(pid: str, text: str, defined: Set[str]) -> List[str]:
    return sorted({m.group(1) for m in KEY_REF.finditer(text) if m.group(2) != pid and m.group(2) in DEFINITIONS and m.group(1) in defined})


def defined_keys() -> Set[str]:
    return {m.group(1) for m in DEFINED_KEY.finditer(catalog_text())}


def plugin_sources(pid: str) -> Dict[Path, str]:
    out: Dict[Path, str] = {}
    for base in (ROOT / "src" / "cplugs" / pid, ROOT / "web" / "src" / "cplugs" / pid):
        for path in base.rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and ".test." not in path.name and "fixtures" not in path.parts and path.is_file():
                out[path] = path.read_text(encoding="utf-8")
    return out


@pytest.mark.parametrize("pid", sorted(DEFINITIONS))
def test_a_plugin_owns_its_catalog_keys_and_reaches_no_other_plugins(pid: str) -> None:
    owns = DEFINITIONS[pid].manifest.owns
    assert all(prefix.startswith(f"cplug.{pid}.") for prefix in owns.strings)
    if pid in slice_paths():
        assert owns.strings, f"{pid} keeps a catalog slice, so it must declare owns.strings"
    reaches = {str(p.relative_to(ROOT)): v for p, text in plugin_sources(pid).items() if (v := own_key_violations(pid, text, defined_keys()))}
    assert reaches == {}, f"{pid} names another plugin's catalog keys: {reaches}"


def test_the_namespace_check_can_fail() -> None:
    defined = {"cplug.save.name", "cplug.share.name"}
    assert own_key_violations("save", "t('cplug.save.name') t('cplug.share.name')", defined) == ["cplug.share.name"]
    assert own_key_violations("save", "t('cplug.ghost.name')", defined) == [], "an unshipped namespace is the orphan test's job"
    assert own_key_violations("flow", "topic 'cplug.huddle.list'", defined) == [], "a push topic is not a catalog key"
    assert "cplug.share.name" in defined_keys() and "cplug.huddle.list" not in defined_keys()
