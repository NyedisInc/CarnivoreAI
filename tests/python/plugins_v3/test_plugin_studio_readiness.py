
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.plugin_studio import readiness, scaffolder


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["no-code", "python", "bash", "widget"])
async def test_readiness_passes_clean_scaffolded_templates(tmp_path: Path, template: str) -> None:
    state_dir = tmp_path / "state"
    name = f"rdy{template.replace('-', '')}"[:20]
    ws, _ = scaffolder.create_workspace(
        state_dir,
        prompt=f"Create a clean {template} plugin.",
        template=template,
        name=name,
    )
    rep = await readiness.check_readiness(Path(ws["folder"]), run_tests=False)
    assert rep["ready"] is True, rep
    assert rep["ok"] is True
    assert rep["summary"]["fail"] == 0
    assert rep["summary"]["undetermined"] == 0
    by_id = {item["id"]: item for item in rep["items"]}
    assert by_id["gate_01_structure"]["status"] == "pass"
    assert by_id["gate_02_schema"]["status"] == "pass"
    assert by_id["gate_03_kind_rules"]["status"] == "pass"
    assert by_id["gate_05_digest"]["status"] == "pass"
    assert by_id["gate_06_static_scans"]["status"] in ("pass", "advisory")
    assert by_id["gate_07_secrets"]["status"] == "pass"
    assert by_id["gate_08_license"]["status"] == "pass"


@pytest.mark.asyncio
async def test_readiness_catches_polyglot_secret_and_missing_license(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    ws_py, _ = scaffolder.create_workspace(state_dir, prompt="Shell test", template="python", name="badpyplug")
    py_folder = Path(ws_py["folder"])

    fake_jwt = ".".join([
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ])
    (py_folder / "main.py").write_text(
        "import subprocess\n"
        f"TOKEN = '{fake_jwt}'\n"
        "subprocess.run('id', shell=True)\n",
        encoding="utf-8",
    )
    rep_py = await readiness.check_readiness(py_folder, run_tests=False)
    assert rep_py["ready"] is False
    by_id = {item["id"]: item for item in rep_py["items"]}
    assert by_id["gate_06_static_scans"]["status"] == "fail"
    assert by_id["gate_07_secrets"]["status"] == "fail"

    ws_nocode, _ = scaffolder.create_workspace(state_dir, prompt="License test", template="no-code", name="nolicplug")
    nocode_folder = Path(ws_nocode["folder"])
    (nocode_folder / "LICENSE.md").unlink()
    rep_lic = await readiness.check_readiness(nocode_folder, run_tests=False)
    assert rep_lic["ready"] is False
    lic_item = {item["id"]: item for item in rep_lic["items"]}["gate_08_license"]
    assert lic_item["status"] == "fail"
    assert lic_item["code"] == "license_file_missing"

    ws_sh, _ = scaffolder.create_workspace(state_dir, prompt="Bash eval test", template="bash", name="badshplug")
    sh_folder = Path(ws_sh["folder"])
    (sh_folder / "run.sh").write_text('#!/bin/bash\neval "echo hi"\n', encoding="utf-8")
    rep_sh = await readiness.check_readiness(sh_folder, run_tests=False)
    assert rep_sh["ready"] is False
    assert {item["id"]: item for item in rep_sh["items"]}["gate_06_static_scans"]["status"] == "fail"


@pytest.mark.asyncio
async def test_readiness_handles_missing_warez_gates_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    ws, _ = scaffolder.create_workspace(state_dir, prompt="Packaged app check", template="no-code", name="pkgplug")
    monkeypatch.setattr(readiness, "REPO_ROOT", tmp_path / "missing_repo")

    rep = await readiness.check_readiness(Path(ws["folder"]), run_tests=False)
    assert rep["ready"] is True
    by_id = {item["id"]: item for item in rep["items"]}
    assert by_id["warez_gates"]["status"] == "unavailable"
    assert by_id["warez_gates"]["code"] == "warez_gates_unavailable"


@pytest.mark.asyncio
async def test_readiness_reports_malformed_toml_and_json_without_crashing(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    ws_toml, _ = scaffolder.create_workspace(state_dir, prompt="Broken TOML test", template="no-code", name="badtoml")
    toml_folder = Path(ws_toml["folder"])
    (toml_folder / "carnivore.toml").write_text("schema = 2\nid = [unclosed\n", encoding="utf-8")

    rep_toml = await readiness.check_readiness(toml_folder, run_tests=False)
    assert rep_toml["ready"] is False
    assert rep_toml["ok"] is False
    by_id_toml = {item["id"]: item for item in rep_toml["items"]}
    assert by_id_toml["check_manifest"]["status"] == "fail"
    assert by_id_toml["gate_02_schema"]["status"] == "fail"

    ws_json, _ = scaffolder.create_workspace(state_dir, prompt="Broken JSON test", template="no-code", name="badjson")
    json_folder = Path(ws_json["folder"])
    (json_folder / "carnivore.toml").unlink()
    (json_folder / "carnivore.json").write_text("{broken json\n", encoding="utf-8")

    rep_json = await readiness.check_readiness(json_folder, run_tests=False)
    assert rep_json["ready"] is False
    assert rep_json["ok"] is False
    by_id_json = {item["id"]: item for item in rep_json["items"]}
    assert by_id_json["check_manifest"]["status"] == "fail"
    assert by_id_json["gate_02_schema"]["status"] == "fail"


@pytest.mark.asyncio
async def test_readiness_reports_warez_gates_timeout_as_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    state_dir = tmp_path / "state"
    ws, _ = scaffolder.create_workspace(state_dir, prompt="Timeout check", template="no-code", name="tmoplug")

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="warez_gates", timeout=0.01)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    rep = await readiness.check_readiness(Path(ws["folder"]), run_tests=False, timeout_s=0.01)
    assert rep["ready"] is False
    assert rep["ok"] is False
    by_id = {item["id"]: item for item in rep["items"]}
    assert by_id["warez_gates"]["status"] == "fail"
    assert by_id["warez_gates"]["code"] == "warez_gates_static_timeout"
