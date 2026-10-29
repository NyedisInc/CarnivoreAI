
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "client" / "css" / "session-sidebar-account-chip.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"rule not found: {selector}"
    return match.group(1)


def test_lurker_avatar_has_no_square_frame() -> None:
    rest = _rule(".session-sidebar-bar__avatar[data-kind='lurker']")
    assert "background: none" in rest
    assert "border-color: transparent" in rest
    hover = _rule(".session-sidebar-bar__account:hover .session-sidebar-bar__avatar[data-kind='lurker']")
    assert "border-color: transparent" in hover
