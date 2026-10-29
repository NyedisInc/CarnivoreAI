
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from scripts.gate import tree_copy as tc

LIGHT = ("src", "client", "config.example.json", "pytest.ini", "web/src/cplugs")


@pytest.fixture(scope="module")
def base_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tc.copy_tree(tmp_path_factory.mktemp("clean-room-base") / "tree", only=LIGHT)


def _probe(tree: Path, tmp_path: Path):
    return tc.run_python(tree, ["-m", "tests.python.gate.probes_import"], tmp_path / "state", tmp_path / "home")


def _with_probe(base: Path, tmp_path: Path) -> Path:
    tree = tc.clone_tree(base, tmp_path / "tree")
    tc.add_probes(tree)
    return tree


def test_the_control_default_tree_imports_with_every_plugin(base_tree: Path, tmp_path: Path) -> None:
    done = _probe(_with_probe(base_tree, tmp_path), tmp_path)
    assert done.returncode == 0, done.stderr[-800:]
    assert tc.last_json(done.stdout)["plugins"] == tc.shipped_ids()


def test_deleting_only_the_folders_leaves_an_app_that_imports(base_tree: Path, tmp_path: Path) -> None:
    tree = _with_probe(base_tree, tmp_path)
    tc.strip_folders(tree, tc.removable_ids())
    done = _probe(tree, tmp_path)
    assert done.returncode == 0, done.stderr[-500:]


def test_removal_as_documented_leaves_an_app_that_imports_without_those_plugins(base_tree: Path, tmp_path: Path) -> None:
    tree = _with_probe(base_tree, tmp_path)
    gone = tc.removable_ids()
    tc.strip_folders(tree, gone)
    done = _probe(tree, tmp_path)
    assert done.returncode == 0, done.stderr[-800:]
    kept = sorted(set(tc.shipped_ids()) - set(gone))
    assert tc.last_json(done.stdout)["plugins"] == kept


@pytest.mark.parametrize("plugin_id", tc.removable_ids())
def test_each_removable_plugin_goes_alone(base_tree: Path, tmp_path: Path, plugin_id: str) -> None:
    tree = _with_probe(base_tree, tmp_path)
    tc.strip_folders(tree, [plugin_id])
    done = _probe(tree, tmp_path)
    assert done.returncode == 0, f"{plugin_id}: {done.stderr[-600:]}"
    assert tc.last_json(done.stdout)["plugins"] == sorted(set(tc.shipped_ids()) - {plugin_id})


def test_the_strip_refuses_a_plugin_that_is_not_there(tmp_path: Path) -> None:
    (tmp_path / "src" / "cplugs").mkdir(parents=True)
    with pytest.raises(tc.TreeCopyError, match="no plugin folder"):
        tc.strip_folders(tmp_path, ["nope"])


def test_not_removable_is_a_real_plugin_and_every_other_plugin_is_in_the_removable_set() -> None:
    assert set(tc.NOT_REMOVABLE) <= set(tc.shipped_ids())
    assert set(tc.removable_ids()) | set(tc.NOT_REMOVABLE) == set(tc.shipped_ids())


def test_core_reaching_into_a_removed_plugin_turns_the_import_red(base_tree: Path, tmp_path: Path) -> None:
    tree = _with_probe(base_tree, tmp_path)
    tc.strip_folders(tree, ["flow"])
    main = tree / "src" / "main.py"
    main.write_text("from src.cplugs import flow  # the planted reach\n" + main.read_text(encoding="utf-8"), encoding="utf-8")
    done = _probe(tree, tmp_path)
    assert done.returncode != 0 and "flow" in done.stderr
