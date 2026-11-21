
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core import ui_preferences
from src.core.keymap import catalog_text, clashes
from src.core.keymap.clashes import KeymapClashError
from src.core.keymap.scopes import scopes_overlap
from src.core.ui_preferences.keymap_checks import check_keymap

REPO = Path(__file__).resolve().parents[3]
REQUIRE_NODE = os.environ.get("CLOUDE_REQUIRE_NODE") == "1"
HAS_NODE = shutil.which("node") is not None
needs_node = pytest.mark.skipif(not HAS_NODE and not REQUIRE_NODE, reason="node is needed to read the browser's registry")

OVERRIDE_SETS = [
    {"mac": {"history.back": ["cmd+k"], "tab.next": ["cmd+1"]}},
    {"mac": {"palette.open": [], "history.back": ["cmd+k"]}},
    {"mac": {"settings.open": ["cmd+k"], "file.save": ["cmd+j"]}},
    {"mac": {"palette.open": ["cmd+j"], "history.back": ["cmd+k"]}},
    {"other": {"palette.open": ["ctrl+shift+j"], "history.back": ["ctrl+shift+k"]}},
    {"mac": {"menu.rename": ["r"]}, "other": {"history.forward": ["ctrl+shift+k"]}},
]


def _node(script: str) -> Any:
    if not HAS_NODE:
        pytest.fail("node is required (CLOUDE_REQUIRE_NODE=1) to read the browser's registry")
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


def _config(keymap: Dict[str, Any] | None) -> Dict[str, Any]:
    return {} if keymap is None else {"ui_preferences": {"schema_version": 1, "revision": 1, "values": {"keymap": keymap}}}


def _write(stored: Dict[str, Any] | None, new: Dict[str, Any]) -> Dict[str, Any]:
    return ui_preferences.apply_changes(_config(stored), ui_preferences.validate_changes({"keymap": new}))[2]


def test_a_write_that_introduces_a_clash_is_refused() -> None:
    with pytest.raises(KeymapClashError) as caught:
        _write(None, {"mac": {"history.back": ["cmd+k"]}})
    assert (caught.value.chord, caught.value.action_id, caught.value.other_id) == ("cmd+k", "history.back", "palette.open")
    assert clashes.label_of("history.back") in str(caught.value) and clashes.label_of("palette.open") in str(caught.value)


def test_a_clash_already_stored_never_blocks_an_unrelated_write() -> None:
    stored = {"mac": {"palette.open": ["cmd+j"], "history.back": ["cmd+j"]}}
    assert clashes.find_clashes("mac", stored)
    unrelated = {"mac": {**stored["mac"], "history.forward": ["cmd+y"]}}
    assert _write(stored, unrelated)["keymap"] == unrelated
    with pytest.raises(KeymapClashError):
        _write(stored, {"mac": {**stored["mac"], "tab.next": ["cmd+j"]}})


def test_free_chord_swap_and_reset_are_accepted() -> None:
    assert check_keymap({"mac": {"history.back": ["cmd+j"]}}) == {"mac": {"history.back": ["cmd+j"]}}
    swap = {"mac": {"palette.open": ["cmd+j"], "history.back": ["cmd+k"]}}
    assert _write(None, swap)["keymap"] == swap
    assert check_keymap(None) is None and _write(swap, {"mac": {}})["keymap"] == {"mac": {}}


def test_the_store_refuses_a_new_clash_with_a_typed_status(tmp_path: Path) -> None:
    from src.core.ui_preferences_store import REJECTED_INVALID, UiPreferencesStore

    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    result = UiPreferencesStore(lambda: path).update({"keymap": {"mac": {"history.back": ["cmd+k"]}}}, expected_revision=None)
    assert result.status == REJECTED_INVALID and clashes.label_of("palette.open") in result.detail


def test_a_missing_catalog_line_is_never_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_text, "read_prefixed", lambda *_a, **_k: {})
    with pytest.raises(KeymapClashError) as caught:
        _write(None, {"mac": {"history.back": ["cmd+k"]}})
    assert str(caught.value) == clashes.CLASH_MESSAGE_KEY
    monkeypatch.setattr(catalog_text, "read_prefixed", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad line")))
    assert catalog_text.catalog_text("keymap.refuse.tab") == "keymap.refuse.tab"


def test_the_shipped_defaults_carry_no_clash() -> None:
    assert clashes.find_clashes("mac", {}) == [] and clashes.find_clashes("other", {}) == []


@needs_node
def test_registry_snapshot_is_the_browser_registry() -> None:
    live = _node(
        "const a = await import('./client/js/keymap/actions.js'); const s = await import('./scripts/keymap/export_registry.mjs');"
        "console.log(JSON.stringify(a.ACTIONS.map(s.slim)))"
    )
    assert clashes.registry() == live, "run: node scripts/keymap/export_registry.mjs"


@needs_node
def test_scope_overlap_matches_the_browser_for_every_scope() -> None:
    scopes = _node(
        "const a = await import('./client/js/keymap/actions.js'); const s = await import('./client/js/keymap/scopes.js');"
        "console.log(JSON.stringify([...new Set([...s.FIXED_SCOPES, ...a.ACTIONS.map((x) => x.scope), 'menu:rail', 'overlay:other'])]))"
    )
    assert len(scopes) >= 31
    pairs = list(itertools.product(scopes, scopes, (False, True)))
    js = _node(
        f"const s = await import('./client/js/keymap/scopes.js'); const pairs = {json.dumps(pairs)};"
        "console.log(JSON.stringify(pairs.map(([a, b, c]) => s.scopesOverlap(a, b, c))))"
    )
    assert js == [scopes_overlap(a, b, c) for a, b, c in pairs]


@needs_node
@pytest.mark.parametrize("overrides", OVERRIDE_SETS)
def test_find_clashes_matches_the_browser_with_overrides(overrides: Dict[str, Any]) -> None:
    for family in ("mac", "other"):
        js = _node(
            "const a = await import('./client/js/keymap/actions.js'); const e = await import('./client/js/keymap/effective.js');"
            f"console.log(JSON.stringify(e.conflicts(a.ACTIONS, '{family}', {json.dumps(overrides)}).map((c) => [c.chord, c.a, c.b])))"
        )
        assert js == [list(c) for c in clashes.find_clashes(family, overrides)]
