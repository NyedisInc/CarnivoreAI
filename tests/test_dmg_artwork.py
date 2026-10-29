
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = REPO_ROOT / "packaging" / "dmg" / "artwork" / "render-background.py"
PACKAGE_JSON = REPO_ROOT / "macOS" / "package.json"
BACKGROUND_SOURCE = REPO_ROOT / "macOS" / "assets" / "dmg" / "background-source.png"
BACKGROUND_TIFF = REPO_ROOT / "macOS" / "assets" / "dmg" / "background.tiff"


def load_renderer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_background", RENDERER)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {RENDERER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def art() -> ModuleType:
    return load_renderer()


@pytest.fixture(scope="module")
def dmg_config() -> dict:
    with PACKAGE_JSON.open("r", encoding="utf-8") as handle:
        return json.load(handle)["build"]["dmg"]


def _tiffutil_info(tiff_path: Path) -> str:
    return subprocess.run(
        ["tiffutil", "-info", str(tiff_path)], capture_output=True, text=True
    ).stdout




def test_the_source_image_is_committed(art: ModuleType) -> None:
    assert BACKGROUND_SOURCE.is_file(), (
        f"{BACKGROUND_SOURCE} is missing; the owner-supplied source art must "
        "be committed so background.png/@2x/.tiff can be re-rendered"
    )


def test_the_source_image_matches_the_declared_dimensions(art: ModuleType) -> None:
    from PIL import Image

    with Image.open(BACKGROUND_SOURCE) as image:
        assert image.size == (art.SOURCE_W, art.SOURCE_H)




def test_window_size_matches_the_dmg_config(art: ModuleType, dmg_config: dict) -> None:
    window = dmg_config["window"]
    assert art.WINDOW_W == window["width"]
    assert art.WINDOW_H + art.TITLEBAR_H + art.STATUS_PATH_BARS_H == window["height"]


def test_icon_positions_match_the_dmg_config(art: ModuleType, dmg_config: dict) -> None:
    contents = dmg_config["contents"]
    app_cell = next(c for c in contents if c["type"] == "file" and "name" not in c)
    link_cell = next(c for c in contents if c["type"] == "link")

    assert (app_cell["x"], app_cell["y"]) == (art.APP_ICON_X, art.ICON_Y)
    assert (link_cell["x"], link_cell["y"]) == (art.LINK_ICON_X, art.ICON_Y)
    assert link_cell["path"] == "/Applications"


def test_icon_size_matches_the_dmg_config(art: ModuleType, dmg_config: dict) -> None:
    assert art.WINDOW_W > 0 and dmg_config["iconSize"] > 0
    assert dmg_config["iconSize"] == 128
    assert dmg_config["iconTextSize"] == 14


def test_the_dmg_uses_the_rendered_background(dmg_config: dict) -> None:
    background = dmg_config.get("background", "")
    assert background, "the dmg block must declare a background"
    assert background.endswith(".tiff"), (
        "the background must be the fused multi-representation tiff; a plain "
        "png is either soft at 2x or half-size at 1x"
    )
    assert (REPO_ROOT / "macOS" / background).is_file(), (
        f"{background} is missing; run packaging/dmg/artwork/render-background.py"
    )




def test_both_icon_centres_fall_inside_the_source_frame_band(art: ModuleType) -> None:
    half_icon = 128 / 2
    assert art.ICON_Y - half_icon >= art.FRAME_TOP, (
        "the icon's top edge sits above the frame"
    )
    assert art.ICON_Y + half_icon <= art.FRAME_BOTTOM, (
        "the icon's bottom edge runs past the frame"
    )
    frame_mid = (art.FRAME_TOP + art.FRAME_BOTTOM) / 2
    assert abs(art.ICON_Y - frame_mid) <= 10


def test_the_two_icon_centres_share_one_y(art: ModuleType) -> None:
    assert art.ICON_Y == round(art._scale_point(art.SOURCE_CROSSHAIR_LEFT)[1])
    assert art.ICON_Y == round(art._scale_point(art.SOURCE_CROSSHAIR_RIGHT)[1])


def test_the_two_icon_centres_are_left_and_right_of_each_other(art: ModuleType) -> None:
    assert art.APP_ICON_X < art.LINK_ICON_X
    assert 0 < art.APP_ICON_X < art.WINDOW_W
    assert 0 < art.LINK_ICON_X < art.WINDOW_W




def test_the_renderer_runs_end_to_end(art: ModuleType, tmp_path: Path) -> None:
    if subprocess.run(
        ["which", "tiffutil"], capture_output=True
    ).returncode != 0:
        pytest.skip("tiffutil not available (ships with macOS)")

    result = subprocess.run(
        [
            "python3", str(RENDERER),
            "--source", str(BACKGROUND_SOURCE),
            "--out-dir", str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    png_1x = tmp_path / "background.png"
    png_2x = tmp_path / "background@2x.png"
    tiff = tmp_path / "background.tiff"
    for path in (png_1x, png_2x, tiff):
        assert path.is_file(), f"{path.name} was not produced"

    from PIL import Image

    with Image.open(png_1x) as image:
        assert image.size == (art.WINDOW_W, art.WINDOW_H)
    with Image.open(png_2x) as image:
        assert image.size == (art.WINDOW_W * 2, art.WINDOW_H * 2)

    info = _tiffutil_info(tiff)
    assert f"Image Width: {art.WINDOW_W} Image Length: {art.WINDOW_H}" in info
    assert (
        f"Image Width: {art.WINDOW_W * 2} Image Length: {art.WINDOW_H * 2}" in info
    ), "the tiff is missing its 2x representation"


def test_the_committed_tiff_has_both_representations_at_the_right_size(
    art: ModuleType,
) -> None:
    if subprocess.run(
        ["which", "tiffutil"], capture_output=True
    ).returncode != 0:
        pytest.skip("tiffutil not available (ships with macOS)")

    assert BACKGROUND_TIFF.is_file()
    info = _tiffutil_info(BACKGROUND_TIFF)
    assert f"Image Width: {art.WINDOW_W} Image Length: {art.WINDOW_H}" in info
    assert (
        f"Image Width: {art.WINDOW_W * 2} Image Length: {art.WINDOW_H * 2}" in info
    ), "the committed tiff is missing its 2x representation"
