
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "release" / "preview-install.sh"
VERIFY_MODULES = REPO / "scripts" / "release" / "verify-node-modules.js"
VERIFY_ASAR = REPO / "scripts" / "release" / "verify-asar.js"
NODE = shutil.which("node")


def _real_macos_modules() -> Path | None:
    top = subprocess.run(
        ["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    for line in top:
        if line.startswith("worktree "):
            nm = Path(line[9:]) / "macOS" / "node_modules"
            if (nm / "semver" / "package.json").exists() and (nm / "@electron" / "asar").exists():
                return nm.resolve()
    return None


REAL_NM = _real_macos_modules()
needs_node = pytest.mark.skipif(NODE is None or REAL_NM is None, reason="node or installed macOS/node_modules missing")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([NODE, *args], capture_output=True, text=True, check=False)


def _macos_dir(tmp_path: Path, installed: dict[str, str], declared: dict[str, str]) -> Path:
    mac = tmp_path / "macOS"
    nm = mac / "node_modules"
    nm.mkdir(parents=True)
    (nm / "semver").symlink_to(REAL_NM / "semver")
    for name, version in installed.items():
        (nm / name).mkdir()
        (nm / name / "package.json").write_text(json.dumps({"name": name, "version": version}))
    (mac / "package.json").write_text(json.dumps({"dependencies": declared}))
    return mac


def test_build_log_is_not_written_inside_the_packed_macos_folder() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "macOS/preview-build.log" not in text
    assert "$build_log" in text and "carnivore-preview-build-" in text
    assert re.search(r'case "\$build_log" in "\$WT/macOS"/\*\)', text), "no guard against a log under macOS/"


def test_build_runs_both_gates_before_the_dmg_is_copied_out() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.index('node "$VERIFY_ASAR"') < text.index('cp "$built" "$OUT_DIR/')
    assert 'node "$VERIFY_MODULES"' in text


@needs_node
def test_stale_modules_are_refused_naming_the_package_and_the_fix(tmp_path: Path) -> None:
    mac = _macos_dir(tmp_path, {"electron": "28.3.3"}, {"electron": "^44.6.0", "electron-updater": "^6.8.9"})
    result = _run(str(VERIFY_MODULES), str(mac))
    assert result.returncode == 1
    assert "electron installed 28.3.3 does not satisfy ^44.6.0" in result.stderr
    assert "electron-updater" in result.stderr and "NOT INSTALLED" in result.stderr
    assert "npm install" in result.stderr


@needs_node
def test_matching_modules_pass(tmp_path: Path) -> None:
    mac = _macos_dir(tmp_path, {"electron": "44.6.1"}, {"electron": "^44.6.0"})
    assert _run(str(VERIFY_MODULES), str(mac)).returncode == 0


APP_MAIN = "module.exports = 1;\n"


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def _pkg(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def _asar_fixture(tmp_path: Path, packed: dict[str, str], source: dict[str, str] | None = None) -> tuple[Path, Path]:
    mac = tmp_path / "macOS"
    (mac / "node_modules" / "@electron").mkdir(parents=True)
    (mac / "node_modules" / "@electron" / "asar").symlink_to(REAL_NM / "@electron" / "asar")
    _write_tree(mac, {"main.js": APP_MAIN, **(source or {})})
    pack = tmp_path / "pack"
    pack.mkdir()
    _write_tree(pack, packed)
    asar_path = tmp_path / "app.asar"
    script = f"require({json.dumps(str(REAL_NM / '@electron' / 'asar'))}).createPackage({json.dumps(str(pack))},{json.dumps(str(asar_path))}).then(()=>0)"
    assert _run("-e", script).returncode == 0
    return asar_path, mac


HOISTED_SOURCE = {
    "node_modules/dep/package.json": _pkg("dep", "2.0.0"),
    "node_modules/dep/index.js": "module.exports = 'v2';\n",
    "node_modules/host/package.json": _pkg("host", "1.0.0"),
    "node_modules/host/index.js": "require('dep');\n",
    "node_modules/host/node_modules/dep/package.json": _pkg("dep", "1.0.0"),
    "node_modules/host/node_modules/dep/index.js": "module.exports = 'v1';\n",
}


def _hoisted_pack(dep_index: str) -> dict[str, str]:
    return {
        "main.js": APP_MAIN,
        "node_modules/host/package.json": _pkg("host", "1.0.0"),
        "node_modules/host/index.js": "require('dep');\n",
        "node_modules/dep/package.json": _pkg("dep", "1.0.0"),
        "node_modules/dep/index.js": dep_index,
    }


@needs_node
def test_asar_gate_passes_an_exact_copy(tmp_path: Path) -> None:
    asar_path, mac = _asar_fixture(tmp_path, {"main.js": APP_MAIN})
    assert _run(str(VERIFY_ASAR), str(asar_path), str(mac)).returncode == 0


@needs_node
def test_asar_gate_fails_a_corrupted_file(tmp_path: Path) -> None:
    asar_path, mac = _asar_fixture(tmp_path, {"main.js": "module.exports = 1;\nGARBAGE(((\n"})
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 1
    assert "MISMATCH: main.js" in result.stderr and "SYNTAX ERROR: main.js" in result.stderr


@needs_node
def test_asar_gate_passes_a_hoisted_dependency_copy(tmp_path: Path) -> None:
    asar_path, mac = _asar_fixture(tmp_path, _hoisted_pack("module.exports = 'v1';\n"), HOISTED_SOURCE)
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 0, result.stderr
    assert "3 packed .js files" in result.stdout and "1 of them from a hoisted copy" in result.stdout


@needs_node
def test_asar_gate_fails_a_corrupted_hoisted_dependency(tmp_path: Path) -> None:
    asar_path, mac = _asar_fixture(tmp_path, _hoisted_pack("module.exports = 'v1';\n// shifted\n"), HOISTED_SOURCE)
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 1
    assert "MISMATCH: node_modules/dep/index.js matches no source copy of dep@1.0.0" in result.stderr


@needs_node
def test_asar_gate_fails_a_dependency_with_no_source_copy(tmp_path: Path) -> None:
    pack = {**_hoisted_pack("module.exports = 'v1';\n"), "node_modules/dep/package.json": _pkg("dep", "3.0.0")}
    asar_path, mac = _asar_fixture(tmp_path, pack, HOISTED_SOURCE)
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 1
    assert "no source copy of dep@3.0.0" in result.stderr


@needs_node
def test_asar_gate_refuses_to_pass_on_nothing(tmp_path: Path) -> None:
    asar_path, mac = _asar_fixture(tmp_path, {"README.txt": "no code\n"})
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 1
    assert "compared no .js files" in result.stderr


@needs_node
def test_asar_gate_refuses_when_no_app_file_was_compared(tmp_path: Path) -> None:
    pack = {k: v for k, v in _hoisted_pack("module.exports = 'v1';\n").items() if k != "main.js"}
    asar_path, mac = _asar_fixture(tmp_path, pack, HOISTED_SOURCE)
    result = _run(str(VERIFY_ASAR), str(asar_path), str(mac))
    assert result.returncode == 1
    assert "none of the app's own .js files" in result.stderr
