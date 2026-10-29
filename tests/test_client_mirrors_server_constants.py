
from __future__ import annotations

import re
from pathlib import Path

from src.core.session_token_usage.model_table import COST_TIER_THRESHOLDS

JS = Path(__file__).resolve().parent.parent / "client" / "js" / "sidebar-help.js"
_PATTERN = re.compile(r"var COST_TIER_THRESHOLDS = \[([^\]]*)\];")


def _thresholds(text: str) -> tuple:
    match = _PATTERN.search(text)
    assert match, "sidebar-help.js no longer declares COST_TIER_THRESHOLDS in the form this test reads"
    return tuple(float(x) for x in match.group(1).split(","))


def test_the_panel_ladder_is_the_model_table_ladder():
    assert _thresholds(JS.read_text()) == tuple(float(x) for x in COST_TIER_THRESHOLDS)


def test_a_doctored_ladder_is_caught():
    doctored = JS.read_text().replace("[2, 8, 16, 32]", "[2, 8, 16, 40]")
    assert _thresholds(doctored) != tuple(float(x) for x in COST_TIER_THRESHOLDS)


def test_the_rebind_prefixes_are_the_product_identity_prefixes():
    from src.core.product_identity import LEGACY_TMUX_SESSION_PREFIXES, TMUX_SESSION_PREFIX

    lib = JS.parents[2] / "web" / "src" / "lib"
    text = (lib / "drawer" / "store-rebind.ts").read_text()
    assert re.search(r"export const CURRENT_PREFIX = TMUX_SESSION_PREFIX;", text), (
        "store-rebind.ts no longer takes CURRENT_PREFIX from product-identity"
    )
    assert re.search(
        r"import \{ LEGACY_TMUX_SESSION_PREFIXES, TMUX_SESSION_PREFIX \} from '\.\./product-identity';", text
    )
    assert re.search(
        r"export const LEGACY_PREFIXES: readonly string\[\] = LEGACY_TMUX_SESSION_PREFIXES;", text
    ), "store-rebind.ts no longer binds LEGACY_PREFIXES to the shared tuple"
    identity = (lib / "product-identity.ts").read_text()
    current = re.search(r"export const TMUX_SESSION_PREFIX = '([^']*)';", identity).group(1)
    legacy = re.findall(
        r"'([^']*)'",
        re.search(
            r"export const LEGACY_TMUX_SESSION_PREFIXES: readonly string\[\] = Object\.freeze\(\[([^\]]*)\]\);",
            identity,
        ).group(1),
    )
    assert current == TMUX_SESSION_PREFIX
    assert tuple(legacy) == tuple(LEGACY_TMUX_SESSION_PREFIXES)
