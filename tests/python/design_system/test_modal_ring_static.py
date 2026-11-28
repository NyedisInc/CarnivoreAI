
from __future__ import annotations

from pathlib import Path

from tests.python.design_system.test_cheap_animations import CHEAP, animated_properties
from tests.python.design_system._sources import css_of

CLIENT = Path(__file__).resolve().parents[3] / "client"
GLOW = CLIENT / "css" / "modal-glow.css"


def test_keyframe_reader_flags_a_custom_property_sweep() -> None:
    sample = "@keyframes x { from { --mg-angle: 0deg } to { --mg-angle: 360deg } }"
    assert animated_properties(sample)["x"] - CHEAP == {"--mg-angle"}


def test_glow_animates_only_transform_and_declares_no_registered_angle() -> None:
    raw = GLOW.read_text(encoding="utf-8")
    css = css_of(GLOW)
    frames = animated_properties(raw)
    for name, props in frames.items():
        assert props <= CHEAP, f"{name} animates {sorted(props - CHEAP)}"
    assert "amb-join-dialog-glow" in css, "modal-glow.css must join the shared 24 fps dialog-glow clock"
    assert "transform: rotate(var(--amb-sheen-deg, 0deg))" in css
    assert "@property" not in css, "a registered angle is a main-thread animation"
    assert "::after" not in css, "the ring is the .mg-sheen child now, not a pseudo on the card"
