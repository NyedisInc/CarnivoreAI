
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = (ROOT / "client" / "css" / "session-sidebar-account-chip.css").read_text(encoding="utf-8")
AVATAR = (ROOT / "web" / "src" / "lib" / "drawer" / "avatar.ts").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"rule not found: {selector}"
    return match.group(1)


def test_lurker_avatar_keeps_the_square_frame() -> None:
    rest = _rule(".session-sidebar-bar__avatar[data-kind='lurker']")
    assert "background" not in rest
    assert "border" not in rest


def test_spiral_is_clipped_by_a_still_mask() -> None:
    mask = _rule(".session-sidebar-bar__avatar > .spiral-mask")
    assert "overflow: hidden" in mask
    assert '<span class="spiral-mask"><svg class="anon spiral spiral-turn"' in AVATAR
