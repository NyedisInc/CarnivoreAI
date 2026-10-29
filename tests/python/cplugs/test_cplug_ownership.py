
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.cplugs.sdk.manifest import ManifestError, parse_manifest
from src.cplugs.sdk.ownership import OwnershipError, parse_ownership
from tests.helpers.catalog_text import catalog_text, slice_paths
from tests.python.cplugs.test_cplug_self_containment import ROOT, plugin_ids

CATALOG = ROOT / "client" / "js" / "i18n" / "catalog.en.js"
CATALOG_KEY = re.compile(r"""['"](cplug\.([a-z0-9]+)\.[^'"]*)['"]\s*:""")


def _manifest(pid: str) -> dict:
    return json.loads((ROOT / "src" / "cplugs" / pid / "cplug.json").read_text(encoding="utf-8"))


def test_a_well_formed_block_parses():
    owns = parse_ownership("save", {"strings": ["cplug.save."], "routes": ["/search"], "styles": ["a/b.css"],
                                          "tests": ["tests/python/cplugs/save/"], "contributions": ["drawer.search_mode"]})
    assert owns.strings == ("cplug.save.",) and owns.contributions == ("drawer.search_mode",)
    assert parse_ownership("save", None).strings == ()
    assert parse_ownership("save", {"files": ["time-machine", "a/b.db"]}).files == ("time-machine", "a/b.db")


@pytest.mark.parametrize("block", [
    {"strings": ["cplug.huddle.x"]},
    {"routes": ["search"]},
    {"routes": ["/../huddle"]},
    {"styles": ["../huddle/a.css"]},
    {"styles": ["/abs.css"]},
    {"tests": ["tests/python/cplugs/huddle/"]},
    {"style_guide": ["web/src/lib/x.svelte"]},
    {"contributions": ["core.everything"]},
    {"files": ["../escape"]},
    {"files": ["/abs"]},
    {"files": ["cplugs/flow"]},
    {"files": ["carnivore.db"]},
    {"files": ["time-machine/*"]},
    {"unknown": []},
    {"strings": ["cplug.save.a", "cplug.save.a"]},
])
def test_a_broken_block_is_refused(block):
    with pytest.raises(OwnershipError):
        parse_ownership("save", block)


def test_the_manifest_refuses_a_broken_block():
    raw = _manifest("save")
    raw["owns"] = {"strings": ["cplug.flow.x"]}
    with pytest.raises(ManifestError):
        parse_manifest(raw)


@pytest.mark.parametrize("pid", plugin_ids())
def test_every_declared_file_exists(pid):
    owns = parse_manifest(_manifest(pid)).owns
    web = ROOT / "web" / "src" / "cplugs" / pid
    missing = [str(web / f) for f in (*owns.styles, *owns.assets) if not (web / f).exists()]
    missing += [t for t in (*owns.tests, *owns.style_guide) if not (ROOT / t).exists()]
    assert missing == []


@pytest.mark.parametrize("pid", plugin_ids())
def test_a_plugin_that_declares_styles_keeps_no_undeclared_css(pid):
    owns = parse_manifest(_manifest(pid)).owns
    if not owns.styles:
        pytest.skip("no styles declared")
    web = ROOT / "web" / "src" / "cplugs" / pid
    found = {p.relative_to(web).as_posix() for p in web.rglob("*.css")}
    assert found - set(owns.styles) == set()


def test_every_plugin_string_key_lives_in_a_real_plugin_namespace():
    ids = set(plugin_ids())
    orphans = sorted({m.group(1) for m in CATALOG_KEY.finditer(catalog_text()) if m.group(2) not in ids})
    assert orphans == []


@pytest.mark.parametrize("pid", sorted(slice_paths()))
def test_a_plugin_catalog_slice_holds_only_its_own_namespace_and_the_shared_file_none_of_it(pid):
    own = {m.group(1) for m in CATALOG_KEY.finditer(slice_paths()[pid].read_text(encoding="utf-8"))}
    assert own and all(k.startswith(f"cplug.{pid}.") for k in own)
    shared = {m.group(1) for m in CATALOG_KEY.finditer(CATALOG.read_text(encoding="utf-8"))}
    assert not {k for k in shared if k.startswith(f"cplug.{pid}.")}


def test_the_five_removable_plugins_all_ship_a_slice_and_declare_owns():
    five = {"share", "unread", "flow", "reviewboard", "save"}
    assert five <= set(slice_paths())
    for pid in five:
        owns = parse_manifest(_manifest(pid)).owns
        assert owns.strings == (f"cplug.{pid}.",) and owns.tests, pid


def test_the_ownership_checks_can_fail():
    ids = {"flow"}
    assert [k for k in ("cplug.flow.a", "cplug.ghost.a") if k.split(".")[1] not in ids] == ["cplug.ghost.a"]
