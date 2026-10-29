import json
from pathlib import Path

from PIL import Image

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1] / "client" / "css" / "themes"
MANIFESTS = sorted(ROOT.glob("*/theme.json"))


def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))


def _check_theme_ships_its_own_sized_artwork_and_readable_heading(path: Path) -> None:
    manifest = json.loads(path.read_text())
    expected_dim = {"carnivore": 0.8, "carnivore-light": 0.99}.get(path.parent.name, 0.9)
    assert manifest["background"]["dim"] == expected_dim
    background = path.parent / manifest["background"]["image"]
    with Image.open(background) as image:
        assert image.size == (1254, 1254)
        image.verify()
    with Image.open(path.parent / "preview.webp") as image:
        assert image.size == (240, 240)
        image.verify()
    assert background.stat().st_size < 1_000_000
    assert (path.parent / "preview.webp").stat().st_size < 30_000
    palette = manifest["cssVars"]
    a, b = sorted((luminance(palette["--color-accent"]), luminance(palette["--color-header-bg"])))
    assert (b + .05) / (a + .05) >= 4.5


def test_theme_ships_its_own_sized_artwork_and_readable_heading() -> None:
    assert_no_offenders(
        "theme ships its own sized artwork and readable heading",
        MANIFESTS,
        _check_theme_ships_its_own_sized_artwork_and_readable_heading,
        label=lambda p: p.parent.name,
    )
