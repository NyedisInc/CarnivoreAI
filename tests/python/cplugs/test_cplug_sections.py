
from __future__ import annotations

from typing import FrozenSet, List, Set, Tuple

from tests.python.cplugs.sections import (
    CPLUGS, PLATFORM_DIRS, ROOT, ROW_ARROW, core_imports, feature_ids, known_modules, platform_files, platform_violations,
    source_dirs,
)

SECTIONS_DOC = ROOT / "docs" / "plugins" / "sections.md"

FEATURE_CORE_KNOWN: Tuple[str, ...] = (
    "crate -> src.core.deepsearch.fallback_hook",
    "flow -> src.core.flow_data.collect.build",
    "flow -> src.core.flow_data.collect.participants",
    "flow -> src.core.flow_data.feed",
    "flow -> src.core.flow_data.live",
    "flow -> src.core.flow_data.tail",
    "save -> src.core.deepsearch.fallback_hook",
)
FEATURE_CORE_KNOWN_CEILING = 7

PLATFORM_FEATURE_KNOWN: Tuple[str, ...] = ()
PLATFORM_FEATURE_KNOWN_CEILING = 0


def feature_core_known(feature_id: str) -> FrozenSet[str]:
    return known_modules(FEATURE_CORE_KNOWN, feature_id)


def platform_breaches() -> List[str]:
    features = feature_ids()
    found = set()
    for path in platform_files():
        for module in platform_violations(path.read_text(), features):
            found.add(f"{path.relative_to(ROOT)}{ROW_ARROW}{module}")
    return sorted(found)


def feature_core_rows() -> Set[str]:
    rows = set()
    for feature in feature_ids():
        known = feature_core_known(feature)
        for path in (CPLUGS / feature).rglob("*.py"):
            rows.update(f"{feature}{ROW_ARROW}{module}" for module in core_imports(path.read_text(), known))
    return rows


def test_the_sections_cover_every_package():
    assert platform_files() and feature_ids()
    assert all((CPLUGS / name / "__init__.py").exists() for name in PLATFORM_DIRS)
    assert not set(PLATFORM_DIRS) & set(feature_ids())
    assert [name for name in source_dirs() if name not in PLATFORM_DIRS and name not in feature_ids()] == [], (
        "a folder under src/plugins belongs to no section: give it an __init__.py (a feature) or add it to PLATFORM_DIRS")
    assert "flow" in feature_ids()


def test_platform_imports_no_feature():
    found = platform_breaches()
    assert [row for row in found if row not in PLATFORM_FEATURE_KNOWN] == [], "platform never imports a feature; never add to PLATFORM_FEATURE_KNOWN"
    assert [row for row in PLATFORM_FEATURE_KNOWN if row not in found] == [], "a fixed row leaves PLATFORM_FEATURE_KNOWN in the same change"
    assert len(PLATFORM_FEATURE_KNOWN) == PLATFORM_FEATURE_KNOWN_CEILING


def test_features_reach_core_only_through_the_known_list():
    found = feature_core_rows()
    known = set(FEATURE_CORE_KNOWN)
    assert len(known) == len(FEATURE_CORE_KNOWN), "a FEATURE_CORE_KNOWN row is listed twice"
    assert sorted(found - known) == [], "reach core through the sdk; never add to FEATURE_CORE_KNOWN"
    assert sorted(known - found) == [], "a row no feature imports leaves FEATURE_CORE_KNOWN and the ceiling drops with it"
    assert len(known) == FEATURE_CORE_KNOWN_CEILING


def test_the_section_checks_can_fail():
    features = ["huddle", "save"]
    assert platform_violations("from src.plugins.huddle import store\nimport src.plugins.save.engine\n", features) == [
        "src.plugins.huddle", "src.plugins.save.engine"]
    assert platform_violations("from src.plugins import huddle\n", features) == ["src.plugins.huddle"]
    assert platform_violations("from src.plugins.sdk import ToolSpec\nfrom src.core.mcp import tools\nfrom . import x\n", features) == []
    save_known = feature_core_known("save")
    assert core_imports("from src.core.deepsearch import fallback_hook\n", save_known) == ["src.core.deepsearch.fallback_hook"]
    assert core_imports("from src.core.deepsearch import index_scope\n", save_known) == ["src.core.deepsearch"]
    assert core_imports("import src.api.auth\nfrom src.plugins.sdk import x\nimport json\n", feature_core_known("huddle")) == ["src.api.auth"]
    assert feature_core_known("huddle") == frozenset()


def test_the_section_map_doc_names_every_platform_package():
    text = SECTIONS_DOC.read_text()
    for name in PLATFORM_DIRS:
        assert f"src/plugins/{name}" in text
    for name in ("web/src/plugins/sdk", "web/src/lib/cplug-ui", "web/src/plugins/host", "tests/python/cplugs/test_cplug_sections.py"):
        assert name in text
