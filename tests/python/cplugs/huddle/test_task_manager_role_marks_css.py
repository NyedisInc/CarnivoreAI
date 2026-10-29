
from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[4] / "client" / "css"
RULE = re.compile(r"\.session-sidebar-row-provider__lead\s*\{([^}]*)\}")


def top_of_the_star() -> int:
    body = next(m.group(1) for m in RULE.finditer((CSS / "session-sidebar-row-controls.css").read_text()) if "top:" in m.group(1))
    return int(re.search(r"top:\s*(-?\d+)px", body).group(1))


def test_the_star_sits_one_or_two_px_lower_than_before():
    assert top_of_the_star() in (-2, -1)


def test_no_density_stylesheet_moves_the_star_again():
    others = [p.name for p in CSS.glob("*.css") if p.name != "session-sidebar-row-controls.css" and "provider__lead" in p.read_text()]
    assert others == []
