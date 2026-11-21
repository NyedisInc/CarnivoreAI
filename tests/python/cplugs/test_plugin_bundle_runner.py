
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "web" / "scripts" / "build-plugin-bundles.mjs"


def listed(web: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(RUNNER), "--list", "--web", str(web)], capture_output=True, text=True, timeout=60)


def test_it_lists_every_plugin_bundle_config_in_order(tmp_path: Path) -> None:
    for plugin in ("zeta", "alpha"):
        folder = tmp_path / "src" / "plugins" / plugin
        folder.mkdir(parents=True)
        (folder / "vite.bundle.config.ts").write_text("export default {}\n")
    (tmp_path / "src" / "plugins" / "plain").mkdir()
    done = listed(tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["src/plugins/alpha/vite.bundle.config.ts", "src/plugins/zeta/vite.bundle.config.ts"]


def test_with_no_plugin_bundles_at_all_it_succeeds_and_builds_nothing(tmp_path: Path) -> None:
    (tmp_path / "src" / "plugins").mkdir(parents=True)
    done = listed(tmp_path)
    assert done.returncode == 0 and done.stdout.strip() == "", done.stderr


def test_a_missing_plugins_folder_is_not_an_error(tmp_path: Path) -> None:
    assert listed(tmp_path).returncode == 0


def test_the_package_build_chain_names_no_plugin() -> None:
    build = (ROOT / "web" / "package.json").read_text()
    assert "publicboard" not in build and "reviewboard" not in build and "build-plugin-bundles.mjs" in build
