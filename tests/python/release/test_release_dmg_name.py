
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HELPER = REPO / "scripts" / "lib" / "release-dmg-name.sh"
ASSETS = {
    "Carnivore-1.16.3-arm64.dmg",
    "Carnivore-1.16.4-universal.dmg",
    "Carnivore-1.16.10-universal.dmg",
    "Carnivore-1.15.0-arm64.dmg",
}


def _run(version: str, prelude: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -u; source "{HELPER}"; {prelude} release_dmg_name "$1"', "_", version],
        capture_output=True, text=True,
    )


def _run_arch(version: str, arch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'set -u; source "{HELPER}"; release_dmg_name "$1" "$2"', "_", version, arch],
        capture_output=True, text=True,
    )


def _name(version: str) -> str:
    done = _run(version)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.mark.parametrize("version", ["1.16.3", "1.15.0", "1.16.4", "1.16.10"])
def test_resolved_name_is_in_the_fake_asset_list(version: str) -> None:
    assert _name(version) in ASSETS


def test_old_release_stays_arm64_and_new_is_universal() -> None:
    assert _name("1.16.3") == "Carnivore-1.16.3-arm64.dmg"
    assert _name("1.16.4") == "Carnivore-1.16.4-universal.dmg"


def test_arch_comes_from_release_arch_json_not_a_literal(tmp_path: Path) -> None:
    fixture = tmp_path / "release-arch.json"
    fixture.write_text('{"dmg_arch": "fancy"}')
    prelude = f'RELEASE_ARCH_JSON="{fixture}";'
    assert _run("1.17.0", prelude).stdout == "Carnivore-1.17.0-fancy.dmg"
    assert _run("1.16.3", prelude).stdout == "Carnivore-1.16.3-arm64.dmg"


def test_leading_v_is_stripped() -> None:
    assert _name("v1.16.4") == "Carnivore-1.16.4-universal.dmg"


TRY = "1.16.5-try.joe-staging.g0fc50d3"


def test_try_build_takes_the_arch_it_was_built_with_never_release_arch_json() -> None:
    want = f"Carnivore-{TRY}-arm64.dmg"
    assert _run(TRY, "").returncode == 2
    assert _run_arch(TRY, "arm64").stdout == want
    assert _run(TRY, "BUILD_ARCH=arm64;").stdout == want


def test_a_try_build_with_no_arch_is_refused_not_read_from_release_arch_json() -> None:
    done = _run(TRY)
    assert done.returncode == 2 and "built arch" in done.stderr and done.stdout == ""


@pytest.mark.parametrize("bad", ["1.16.4+build", "abc", "", "vv1.2.3", "1..2"])
def test_a_malformed_version_is_refused_cleanly(bad: str) -> None:
    done = _run(bad)
    assert done.returncode != 0
    assert "not a release version" in done.stderr and done.stdout == ""


def test_both_lookups_use_the_helper_not_their_own_pattern() -> None:
    for rel in ("scripts/deploy-dmg.sh", "scripts/release/preview-install.sh"):
        text = (REPO / rel).read_text()
        assert "release_dmg_name" in text
        assert "-$V-arm64.dmg" not in text and "$INSTALLED_VERSION-arm64.dmg" not in text
