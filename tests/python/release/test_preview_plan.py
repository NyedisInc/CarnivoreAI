
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts.release import preview_plan
from scripts.release.preview_plan import (
    PlanError,
    classify,
    installed_ref,
    mint_preview_version,
    mint_try_version,
    try_slug,
)
from src.core.update_check import parse_version

REPO = Path(__file__).resolve().parents[3]
PACKAGE_JSON_PATH = REPO / "macOS" / "package.json"


@pytest.fixture(scope="module")
def package_json() -> dict:
    return json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))


def test_preview_version_is_next_patch_prerelease_and_never_a_release() -> None:
    version = mint_preview_version("v1.12.19", 27, "344956712237")
    assert version == "1.12.20-preview.27.g3449567"
    assert parse_version(version) is None
    assert mint_preview_version("v1.12.19", 0, "0123456789").endswith(".g0123456")


def test_installed_ref_round_trips_a_preview_and_maps_a_release_to_its_tag() -> None:
    assert installed_ref(mint_preview_version("v1.12.19", 27, "344956712237")) == "3449567"
    assert installed_ref("1.12.19") == "v1.12.19"
    with pytest.raises(PlanError):
        installed_ref("1.12.19-3-gabc1234")
    with pytest.raises(PlanError):
        mint_preview_version("v1.12.20-preview.1.gabcdef0", 1, "abcdef0")


def test_try_version_is_marked_round_trips_and_is_never_a_release() -> None:
    slug = try_slug("adamdev/feat/Sidebar_Fix")
    assert slug == "feat-sidebar-fix"
    version = mint_try_version("v1.12.19", slug, "344956712237")
    assert version == "1.12.20-try.feat-sidebar-fix.g3449567"
    assert installed_ref(version) == "3449567"
    assert parse_version(version) is None
    assert try_slug("--__--") == "ref"
    assert len(try_slug("x" * 80)) <= preview_plan.TRY_SLUG_MAX
    with pytest.raises(PlanError):
        mint_try_version("v1.12.19", "Not_Reduced", "3449567")
    with pytest.raises(PlanError):
        installed_ref("1.12.20-try.Bad_Slug.g3449567")


@pytest.mark.parametrize(
    ("paths", "decision"),
    [
        (["web/src/a.svelte", "client/dist/app.js", "features/index.json",
          "features/changes/x.json", "FEATURES.md", "docs/x.md"], "hot-sync"),
        (["client/js/app.js", "src/main.py"], "build"),
        (["web/src/a.ts", "hosted/site/site.css", "tests/test_x.py", "docs/x.md"], "nothing"),
        (["macOS/main.js"], "build"),
        (["macOS/scripts/adhoc-sign.js"], "build"),
        (["requirements.txt"], "build"),
        (["scripts/session_journal.py"], "build"),
        (["nuke.sh"], "build"),
        (["scripts/features.py"], "nothing"),
    ],
)
def test_classify_reads_what_ships_from_the_real_build_config(
    package_json: dict, paths: list[str], decision: str
) -> None:
    assert classify(paths, package_json).decision == decision


def test_classify_refuses_an_empty_diff(package_json: dict) -> None:
    with pytest.raises(PlanError):
        classify([], package_json)


def test_set_package_version_changes_only_the_top_level_version() -> None:
    text = PACKAGE_JSON_PATH.read_text(encoding="utf-8")
    updated = preview_plan.set_package_version(text, "1.12.20-preview.27.g3449567")
    changed = [(a, b) for a, b in zip(text.splitlines(), updated.splitlines()) if a != b]
    assert len(changed) == 1
    assert json.loads(updated)["version"] == "1.12.20-preview.27.g3449567"
    assert json.loads(updated)["devDependencies"] == json.loads(text)["devDependencies"]
    assert preview_plan.deps_key(json.loads(updated)) == preview_plan.deps_key(json.loads(text))


def test_preview_pins_the_same_signature_requirement_as_the_deploy() -> None:
    def req(path: Path) -> str:
        match = re.search(r"^REQ='([^']+)'$", path.read_text(encoding="utf-8"), re.MULTILINE)
        assert match, f"no REQ= line in {path}"
        return match.group(1)

    assert req(REPO / "scripts" / "release" / "preview-install.sh") == req(REPO / "scripts" / "deploy-dmg.sh")


SCRIPT = REPO / "scripts" / "release" / "preview-install.sh"


def _print_config(tmp_path: Path, **env: str) -> dict[str, str]:
    clean = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    clean.update(env)
    out = subprocess.run(
        ["/bin/bash", str(SCRIPT), "--print-config"], env=clean, capture_output=True, text=True, check=True
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def test_defaults_are_joes_when_the_usb_volume_is_mounted(tmp_path: Path) -> None:
    usb = tmp_path / "usb"
    usb.mkdir()
    cfg = _print_config(tmp_path, PREVIEW_USB_VOLUME=str(usb))
    assert cfg["SIGN_IDENTITY"] == "Carnivore Development"
    assert cfg["DR_REQ"] == _req(SCRIPT)
    assert cfg["OUT_DIR"] == f"{usb}/releases/previews"
    assert cfg["RELEASES_DIR"] == f"{usb}/releases"


def test_unmounted_usb_falls_back_to_a_home_folder(tmp_path: Path) -> None:
    cfg = _print_config(tmp_path, PREVIEW_USB_VOLUME=str(tmp_path / "absent"))
    assert cfg["OUT_DIR"] == f"{tmp_path}/carnivore-previews"
    assert cfg["RELEASES_DIR"] == cfg["OUT_DIR"]
    explicit = _print_config(tmp_path, PREVIEW_USB_VOLUME=str(tmp_path / "absent"), PREVIEW_OUT_DIR="/x/y")
    assert explicit["OUT_DIR"] == "/x/y"


def test_signing_overrides_and_ad_hoc_skips_the_requirement(tmp_path: Path) -> None:
    named = _print_config(tmp_path, PREVIEW_SIGN_IDENTITY="Me", PREVIEW_DESIGNATED_REQUIREMENT="none")
    assert (named["SIGN_IDENTITY"], named["DR_REQ"]) == ("Me", "none")
    assert _print_config(tmp_path, PREVIEW_SIGN_IDENTITY="-")["DR_REQ"] == "none"
    assert _print_config(tmp_path, PREVIEW_SIGN_IDENTITY="-", PREVIEW_DESIGNATED_REQUIREMENT="x")["DR_REQ"] == "x"
    assert _print_config(tmp_path, PREVIEW_SIGN_IDENTITY="Me")["DR_REQ"] == _req(SCRIPT)


def _req(path: Path) -> str:
    match = re.search(r"^REQ='([^']+)'$", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match
    return match.group(1)
