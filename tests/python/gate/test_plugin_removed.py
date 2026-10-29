
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator

import pytest

from scripts.gate import tree_copy as tc
from src.cplugs.host import dependencies, developer_mode, runtime
from tests.python.gate import cycle
from scripts.gate.known_defects import KNOWN
from tests.python.gate.test_plugin_cycle import build_version

LIGHT = ("src", "client", "config.example.json", "pytest.ini", "web/src")
CHECKS = ("listed_as_removed", "row_404", "enable_404", "routes_404", "tools_gone", "purge_priced", "purge_runs", "files_gone",
          "kept_stores_stay", "state_entry_gone", "strings_not_served", "styles_not_served")
REMOVABLE = tc.removable_ids()
_RESULTS: Dict[str, Dict[str, list]] = {}


@pytest.fixture(scope="module")
def base_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tc.copy_tree(tmp_path_factory.mktemp("removed-base") / "tree", only=LIGHT)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies, "app_version", build_version)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(runtime, "_host", None)


def run_removed(plugin_id: str, base: Path, work: Path, mutate=None) -> Dict[str, list]:
    left = cycle.install_and_leave(plugin_id, work)
    tree = tc.clone_tree(base, work / "tree")
    tc.add_probes(tree)
    tc.strip_folders(tree, [plugin_id])
    if mutate is not None:
        mutate(tree)
    arg = {"plugin_id": plugin_id, "routes": left.routes, "tools": left.tools, "namespace": left.namespace, "css_prefix": left.css_prefix,
           "removed": [str(p) for p in left.written["removed"]], "kept": [str(p) for p in left.written["kept"]]}
    done = tc.run_python(tree, ["-m", "tests.python.gate.probes_removed", json.dumps(arg)], left.state_dir, work / "home")
    assert done.returncode == 0, f"{plugin_id}: the stripped app did not run the probe: {done.stderr[-800:]}"
    return tc.last_json(done.stdout)  # type: ignore[return-value]


@pytest.fixture(scope="module", autouse=True)
def _dump() -> Iterator[None]:
    yield
    out = os.environ.get("GATE_REMOVED_OUT")
    if out and _RESULTS:
        Path(out).write_text(json.dumps(_RESULTS, indent=1), encoding="utf-8")


@pytest.fixture(scope="module")
def probed(base_tree: Path, tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Dict[str, list]]:
    return {}


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("plugin_id", REMOVABLE)
def test_removed_plugin(probed, base_tree, tmp_path_factory, monkeypatch, plugin_id: str, check: str) -> None:
    if plugin_id not in probed:
        probed[plugin_id] = run_removed(plugin_id, base_tree, tmp_path_factory.mktemp(f"removed-{plugin_id}"))
        _RESULTS[plugin_id] = probed[plugin_id]
    ok, detail = probed[plugin_id][check]
    key = f"removed:{plugin_id}:{check}"
    if key in KNOWN:
        assert not ok, f"{key} now passes: #{KNOWN[key][0]} is fixed, delete the entry from scripts/gate/known_defects.py"
        pytest.xfail(f"#{KNOWN[key][0]}: {detail[:200]}")
    assert ok, f"{plugin_id} / {check}: {detail}"


def test_not_removable_plugins_are_left_out_on_purpose() -> None:
    assert set(REMOVABLE).isdisjoint(tc.NOT_REMOVABLE) and set(tc.NOT_REMOVABLE) <= set(tc.shipped_ids())


def test_a_broken_purge_in_the_copy_is_caught(base_tree: Path, tmp_path: Path) -> None:
    def break_purge(tree: Path) -> None:
        guard = tree / "src" / "cplugs" / "host" / "purge_guard.py"
        text = guard.read_text(encoding="utf-8")
        assert "def purge(folder: Path, plugin_id: str, plugins_root: Path, key: Optional[str] = None) -> PurgePlan:" in text
        guard.write_text(text.replace("def purge(folder: Path, plugin_id: str, plugins_root: Path, key: Optional[str] = None) -> PurgePlan:",
                                      "def purge(folder: Path, plugin_id: str, plugins_root: Path, key: Optional[str] = None) -> PurgePlan:\n    return plan(folder, plugin_id)  # the planted break", 1),
                         encoding="utf-8")

    result = run_removed("unread", base_tree, tmp_path, mutate=break_purge)
    assert result["files_gone"][0] is False, result["files_gone"]
    assert result["purge_runs"][0] is True, "the purge route itself still answers, only the deletion was broken"


def test_a_planted_string_key_in_the_copy_is_caught(base_tree: Path, tmp_path: Path) -> None:
    def plant(tree: Path) -> None:
        catalog = tree / "client" / "js" / "i18n" / "catalog.en.js"
        catalog.write_text(catalog.read_text(encoding="utf-8") + "\n  'cplug.unread.planted': 'x',\n", encoding="utf-8")

    result = run_removed("unread", base_tree, tmp_path, mutate=plant)
    assert result["strings_not_served"][0] is False, result["strings_not_served"]
