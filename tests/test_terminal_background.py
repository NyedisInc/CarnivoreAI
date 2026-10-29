
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_termbg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_termbg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import themes_routes
from src.core import terminal_background as tb
from src.core.sessions.background_store import SessionBackgroundStore
from src.models import ThemeBackgroundManifest




def test_accepts_a_plain_image_filename() -> None:
    assert tb.safe_image_filename("grid.png") == "grid.png"
    assert tb.safe_image_filename("city_at_night.jpg") == "city_at_night.jpg"


@pytest.mark.parametrize(
    "value",
    ["../secrets.png", "..", "a/../b.png", "x..png/y.png"],
)
def test_refuses_traversal(value: str) -> None:
    with pytest.raises(tb.UnsafeImageName) as excinfo:
        tb.safe_image_filename(value)
    assert excinfo.value.reason in {"traversal", "separator"}


@pytest.mark.parametrize(
    "value",
    ["sub/grid.png", "/etc/passwd.png", "dir\\grid.png", "\\\\host\\share.png"],
)
def test_refuses_separator(value: str) -> None:
    with pytest.raises(tb.UnsafeImageName) as excinfo:
        tb.safe_image_filename(value)
    assert excinfo.value.reason == "separator"


@pytest.mark.parametrize(
    "value",
    [
        "http://evil.example/x.png",
        "https://evil.example/x.png",
        "data:image/png;base64,AAAA",
        "file:///etc/hosts.png",
        "C:grid.png",
    ],
)
def test_refuses_anything_that_could_be_a_url(value: str) -> None:
    with pytest.raises(tb.UnsafeImageName) as excinfo:
        tb.safe_image_filename(value)
    assert excinfo.value.reason in {"scheme", "separator"}


def test_refuses_a_percent_escape() -> None:
    with pytest.raises(tb.UnsafeImageName) as excinfo:
        tb.safe_image_filename("grid%2e%2e.png")
    assert excinfo.value.reason == "escape"


@pytest.mark.parametrize("value", ["grid.svg", "grid.html", "grid", "grid.js"])
def test_refuses_a_non_image_extension(value: str) -> None:
    with pytest.raises(tb.UnsafeImageName) as excinfo:
        tb.safe_image_filename(value)
    assert excinfo.value.reason == "extension"


@pytest.mark.parametrize("value", ["", None, 12, b"grid.png", ".hidden.png", "a" * 200])
def test_refuses_everything_that_is_not_a_plain_name(value: object) -> None:
    with pytest.raises(tb.UnsafeImageName):
        tb.safe_image_filename(value)


def test_the_manifest_model_refuses_the_same_names() -> None:
    assert ThemeBackgroundManifest(image="ok.png").image == "ok.png"
    with pytest.raises(Exception):
        ThemeBackgroundManifest(image="../ok.png")


def test_the_manifest_clamps_the_dim_instead_of_refusing_it() -> None:
    assert ThemeBackgroundManifest(image="a.png", dim=7).dim == 1.0
    assert ThemeBackgroundManifest(image="a.png", dim=-4).dim == 0.0
    assert ThemeBackgroundManifest(image="a.png").dim == tb.DEFAULT_DIM




def test_a_dim_that_is_not_a_number_falls_back_rather_than_to_an_edge() -> None:
    assert tb.clamp_dim("dark") == tb.DEFAULT_DIM
    assert tb.clamp_dim(None) == tb.DEFAULT_DIM
    assert tb.clamp_dim(float("nan")) == tb.DEFAULT_DIM
    assert tb.clamp_dim(True) == tb.DEFAULT_DIM
    assert tb.clamp_dim(1.7) == 1.0
    assert tb.clamp_dim(-3) == 0.0




def _write_theme(root, theme_id, manifest):
    d = root / theme_id
    d.mkdir(parents=True)
    (d / "theme.json").write_text(json.dumps(manifest))
    return d


def test_a_declared_but_missing_image_drops_the_image_not_the_theme(tmp_path):
    d = _write_theme(
        tmp_path,
        "demo",
        {
            "id": "demo",
            "name": "Demo",
            "description": "d",
            "background": {"image": "missing.png"},
        },
    )
    manifest = themes_routes._load_manifest(d, "builtin")
    assert manifest is not None, "the theme must survive"
    assert manifest.background is None, "the image must not"


def test_the_bundled_carnivore_theme_ships_its_picture():
    root = themes_routes._bundled_themes_root()
    manifest = themes_routes._load_manifest(root / "carnivore", "builtin")
    assert manifest is not None
    assert manifest.background is not None, (
        "the missing-file drop fired: client/css/themes/carnivore/"
        "background.webp is not in the package"
    )
    assert manifest.background.image == "background.webp"
    assert manifest.background.dim == 0.8


def test_a_theme_naming_an_escape_is_skipped_entirely(tmp_path):
    d = _write_theme(
        tmp_path,
        "evil",
        {
            "id": "evil",
            "name": "Evil",
            "description": "d",
            "background": {"image": "../../../../etc/passwd"},
        },
    )
    assert themes_routes._load_manifest(d, "builtin") is None


def test_a_present_image_survives_the_scan(tmp_path):
    d = _write_theme(
        tmp_path,
        "good",
        {
            "id": "good",
            "name": "Good",
            "description": "d",
            "background": {"image": "grid.png", "dim": 0.85},
        },
    )
    (d / "grid.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = themes_routes._load_manifest(d, "builtin")
    assert manifest is not None
    assert manifest.background is not None
    assert manifest.background.image == "grid.png"
    assert manifest.background.dim == 0.85




def test_the_store_round_trips_through_its_file(tmp_path):
    path = tmp_path / "session_backgrounds.json"
    store = SessionBackgroundStore(path=lambda: path)
    store.set("cloude_api", theme_id="matrix", dim=0.9, disabled=False)

    reread = SessionBackgroundStore(path=lambda: path)
    reread.load()
    assert reread.get("cloude_api") == {
        "theme_id": "matrix",
        "dim": 0.9,
        "disabled": False,
        "image": None,
    }


def test_an_override_that_says_nothing_is_removed(tmp_path):
    path = tmp_path / "session_backgrounds.json"
    store = SessionBackgroundStore(path=lambda: path)
    store.set("cloude_api", theme_id="matrix", dim=None, disabled=False)
    assert store.get("cloude_api") is not None
    store.set("cloude_api", theme_id=None, dim=None, disabled=False)
    assert store.get("cloude_api") is None


def test_a_corrupt_file_is_an_empty_map_and_not_a_crash(tmp_path):
    path = tmp_path / "session_backgrounds.json"
    path.write_text("{not json at all")
    store = SessionBackgroundStore(path=lambda: path)
    store.load()
    assert store.overrides == {}


def test_a_stored_dim_is_clamped_on_the_way_in(tmp_path):
    path = tmp_path / "session_backgrounds.json"
    path.write_text(json.dumps({"cloude_api": {"dim": 42}}))
    store = SessionBackgroundStore(path=lambda: path)
    store.load()
    assert store.get("cloude_api")["dim"] == 1.0



_JS_SUITE = ROOT / "tests" / "test_terminal_background.node.mjs"


@pytest.mark.skipif(
    __import__("subprocess").run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_the_client_half_agrees() -> None:
    import subprocess

    result = subprocess.run(
        ["node", str(_JS_SUITE)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, (
        f"terminal background JS suite failed:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )




def test_csp_allows_the_object_url_the_uploaded_picture_is_painted_through():
    from src.security_headers import build_csp

    directives = {
        part.split(" ", 1)[0]: part.split(" ", 1)[1]
        for part in (p.strip() for p in build_csp().split(";"))
        if part and " " in part
    }
    assert "blob:" in directives["img-src"]


def test_csp_widens_images_only_and_never_scripts():
    from src.security_headers import build_csp

    directives = {
        part.split(" ", 1)[0]: part.split(" ", 1)[1]
        for part in (p.strip() for p in build_csp().split(";"))
        if part and " " in part
    }
    assert "blob:" not in directives["script-src"]
    assert "blob:" not in directives["default-src"]
    assert "blob:" not in directives["connect-src"]
    assert len(directives) >= 6
