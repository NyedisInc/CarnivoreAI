
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator

import pytest

from src.cplugs.host import dependencies, developer_mode, runtime
from tests.python.gate import cycle
from scripts.gate.known_defects import KNOWN

IDS = sorted(d.id for d in runtime.definitions())
REPO = Path(__file__).resolve().parents[3]


def build_version() -> str:
    return json.loads((REPO / "macOS" / "package.json").read_text(encoding="utf-8"))["version"]


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Dict[str, cycle.Outcome]]:
    results: Dict[str, cycle.Outcome] = {}
    patch = pytest.MonkeyPatch()
    patch.setattr(developer_mode, "is_on", lambda: True)
    patch.setattr(runtime, "_host", None)
    patch.setattr(dependencies, "app_version", build_version)
    yield results
    patch.undo()
    out = os.environ.get("GATE_MATRIX_OUT")
    if out and results:
        cycle.dump([results[i] for i in sorted(results)], Path(out))


def _outcome(outcomes: Dict[str, cycle.Outcome], tmp_path_factory: pytest.TempPathFactory, plugin_id: str) -> cycle.Outcome:
    if plugin_id not in outcomes:
        outcomes[plugin_id] = cycle.run_cycle(plugin_id, tmp_path_factory.mktemp(f"cycle-{plugin_id}"))
    return outcomes[plugin_id]


@pytest.mark.parametrize("check", cycle.CHECKS)
@pytest.mark.parametrize("plugin_id", IDS)
def test_plugin_cycle(outcomes, tmp_path_factory, plugin_id: str, check: str) -> None:
    status, detail = _outcome(outcomes, tmp_path_factory, plugin_id).checks[check]
    key = f"cycle:{plugin_id}:{check}"
    if key in KNOWN:
        assert status == cycle.FAIL, f"{key} now passes: #{KNOWN[key][0]} is fixed, delete the entry from scripts/gate/known_defects.py"
        pytest.xfail(f"#{KNOWN[key][0]}: {detail[:200]}")
    if status == cycle.NA:
        pytest.skip(f"n/a: {detail}")
    assert status == cycle.PASS, f"{plugin_id} / {check}: {detail}"


def test_every_check_ran_for_every_plugin(outcomes, tmp_path_factory) -> None:
    for pid in IDS:
        assert set(_outcome(outcomes, tmp_path_factory, pid).checks) == set(cycle.CHECKS), pid


def test_the_cycle_table_prints(outcomes, tmp_path_factory, capsys) -> None:
    text = cycle.table([_outcome(outcomes, tmp_path_factory, pid) for pid in IDS])
    with capsys.disabled():
        print("\n" + text)
    assert len(text.splitlines()) == len(IDS) + 1


@pytest.mark.parametrize("plugin_id", IDS)
def test_no_plugin_needs_a_newer_app_than_the_build(plugin_id: str) -> None:
    manifest = runtime.find(plugin_id).manifest
    assert dependencies.version_unmet(manifest, build_version()) is None, f"{plugin_id} needs {manifest.min_app_version}, the build is {build_version()}"


def test_a_known_entry_for_a_cell_that_passes_is_a_failure(outcomes, tmp_path_factory, monkeypatch) -> None:
    monkeypatch.setitem(KNOWN, "cycle:share:enable", (1, "a fixture entry"))
    with pytest.raises(AssertionError, match="now passes"):
        test_plugin_cycle(outcomes, tmp_path_factory, "share", "enable")
