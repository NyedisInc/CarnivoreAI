
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "release" / "preview-install.sh"


def _config() -> dict[str, str]:
    out = subprocess.run(
        ["bash", str(SCRIPT), "--print-config"],
        capture_output=True, text=True, check=True, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-home", "PREVIEW_OUT_DIR": "/nonexistent-out"},
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_build_flags_pin_one_arch_over_the_universal_targets() -> None:
    args = _config()["BUILD_ARGS"].split()
    assert "--arm64" in args and {"dmg", "zip"} <= set(args)


def test_checked_app_folder_is_where_that_arch_builds() -> None:
    arch = next(a[2:] for a in _config()["BUILD_ARGS"].split() if a in ("--arm64", "--x64"))
    assert _config()["BUILT_APP_DIR"] == f"dist/mac-{arch}/Carnivore.app"


def test_script_has_no_second_spelling_of_the_build_command_or_app_folder() -> None:
    code = [l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#")]
    text = "\n".join(code)
    assert 'electron-builder "${BUILD_ARGS[@]}"' in text
    assert text.count("mac-arm64") == 0
    stray = [l for l in code if "-arm64.dmg" in l]
    assert stray == []
