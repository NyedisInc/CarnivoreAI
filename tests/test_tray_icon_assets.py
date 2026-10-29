
from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL", reason="Pillow is required to inspect the icons")
from PIL import Image  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "macOS" / "assets"

EXPECTED_1X_EDGE = 22
EXPECTED_2X_EDGE = 44

ICON_FILES = {
    "": ASSETS_DIR / "iconTemplate.png",
    "@2x": ASSETS_DIR / "iconTemplate@2x.png",
}


@pytest.mark.parametrize("scale", ["", "@2x"])
def test_the_icon_file_exists(scale: str) -> None:
    assert ICON_FILES[scale].exists(), f"missing tray icon: {ICON_FILES[scale]}"


def test_the_icon_is_exactly_the_size_appkit_has_always_loaded() -> None:
    with Image.open(ICON_FILES[""]) as img:
        assert img.size == (EXPECTED_1X_EDGE, EXPECTED_1X_EDGE), (
            f"iconTemplate.png is {img.size}, expected "
            f"({EXPECTED_1X_EDGE}, {EXPECTED_1X_EDGE})"
        )
    with Image.open(ICON_FILES["@2x"]) as img:
        assert img.size == (EXPECTED_2X_EDGE, EXPECTED_2X_EDGE), (
            f"iconTemplate@2x.png is {img.size}, expected "
            f"({EXPECTED_2X_EDGE}, {EXPECTED_2X_EDGE})"
        )


@pytest.mark.parametrize("scale", ["", "@2x"])
def test_the_icon_carries_an_alpha_channel(scale: str) -> None:
    with Image.open(ICON_FILES[scale]) as img:
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        assert alpha.getextrema() != (255, 255), (
            f"iconTemplate{scale}.png has no transparency; a template image "
            "needs the shape carried in alpha, not a filled rectangle"
        )


@pytest.mark.parametrize("scale", ["", "@2x"])
def test_every_opaque_pixel_is_black(scale: str) -> None:
    with Image.open(ICON_FILES[scale]) as img:
        rgba = img.convert("RGBA")
        pixels = rgba.load()
        width, height = rgba.size
        offenders = [
            (x, y, pixels[x, y])
            for y in range(height)
            for x in range(width)
            if pixels[x, y][3] > 0 and pixels[x, y][:3] != (0, 0, 0)
        ]
        assert not offenders, (
            f"iconTemplate{scale}.png has {len(offenders)} opaque pixel(s) "
            f"that are not black, e.g. {offenders[:5]}"
        )


@pytest.mark.parametrize("scale", ["", "@2x"])
def test_the_mark_is_actually_drawn(scale: str) -> None:
    with Image.open(ICON_FILES[scale]) as img:
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        width, height = rgba.size
        histogram = alpha.histogram()
        opaque_pixels = sum(histogram[1:])
        total_pixels = width * height
        coverage = opaque_pixels / total_pixels
        assert opaque_pixels > 0, f"iconTemplate{scale}.png is fully transparent"
        assert coverage >= 0.05, (
            f"iconTemplate{scale}.png draws only {coverage:.1%} of its pixels "
            "opaque, which reads as blank at menu-bar size"
        )


PADDING_TARGETS: dict[str, dict[str, int]] = {
    "": {"content_w": 20, "content_h": 15, "left": 1, "top": 4, "right": 1, "bottom": 3},
    "@2x": {"content_w": 40, "content_h": 30, "left": 2, "top": 8, "right": 2, "bottom": 6},
}

PADDING_TOLERANCE = 2


@pytest.mark.parametrize("scale", ["", "@2x"])
def test_the_mark_has_breathing_room_on_every_side(scale: str) -> None:
    target = PADDING_TARGETS[scale]
    with Image.open(ICON_FILES[scale]) as img:
        width, height = img.size
        bbox = img.getchannel("A").getbbox()
        assert bbox is not None, f"iconTemplate{scale}.png is fully transparent"
        content_w = bbox[2] - bbox[0]
        content_h = bbox[3] - bbox[1]
        padding = {
            "left": bbox[0],
            "top": bbox[1],
            "right": width - bbox[2],
            "bottom": height - bbox[3],
        }

        for side, value in padding.items():
            assert value > 0, (
                f"iconTemplate{scale}.png has zero {side} padding; the mark "
                "touches that edge of the canvas"
            )

        measured = {"content_w": content_w, "content_h": content_h, **padding}
        drift = {
            key: measured[key] - target[key]
            for key in target
            if abs(measured[key] - target[key]) > PADDING_TOLERANCE
        }
        assert not drift, (
            f"iconTemplate{scale}.png measured {measured} vs target {target}, "
            f"outside the {PADDING_TOLERANCE}px tolerance on: {drift}"
        )

        assert padding["left"] == padding["right"] or (
            abs(padding["left"] - padding["right"]) <= 1
        ), (
            f"iconTemplate{scale}.png is not symmetric side to side: left="
            f"{padding['left']}, right={padding['right']}"
        )


def test_the_three_strokes_are_still_separate_at_1x() -> None:
    with Image.open(ICON_FILES[""]) as img:
        rgba = img.convert("RGBA")
        pixels = rgba.load()
        width = rgba.size[0]

        for y in (8, 11, 14):
            runs = 0
            in_run = False
            for x in range(width):
                alpha = pixels[x, y][3]
                if alpha > 60 and not in_run:
                    runs += 1
                    in_run = True
                elif alpha <= 60:
                    in_run = False
            assert runs == 3, (
                f"row y={y} has {runs} stroke run(s) of alpha>60, expected 3 "
                "separate strokes"
            )


def test_no_generated_per_state_dot_assets_remain() -> None:
    old_per_state_icon_dir = ASSETS_DIR / "tray"
    assert not old_per_state_icon_dir.exists(), (
        f"{old_per_state_icon_dir} still exists; it held the removed "
        "per-state status-dot icons and nothing loads it any more"
    )


def test_the_tray_icon_generator_script_is_gone() -> None:
    old_generator = REPO_ROOT / "scripts" / "generate-tray-icons.py"
    assert not old_generator.exists(), (
        f"{old_generator} still exists; it only ever generated the removed "
        "per-state tray icons"
    )
