from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"

REMOVED_TUNNEL_DISTRIBUTIONS = {"cloudflare"}

REMOVED_TUNNEL_MODULES = ("cloudflare", "CloudFlare")

PRODUCT_ROOTS = ("src", "scripts", "packaging", "verify")

_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9._-]+)")


def declared_distributions() -> set[str]:
    names: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _REQUIREMENT_NAME.match(line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def test_parser_sees_the_dependencies_that_are_really_declared():
    declared = declared_distributions()
    assert "fastapi" in declared
    assert "pydantic" in declared
    assert len(declared) >= 10


def test_no_removed_tunnel_distribution_is_declared():
    declared = declared_distributions()
    leaked = REMOVED_TUNNEL_DISTRIBUTIONS & declared
    assert not leaked, (
        f"requirements.txt declares {sorted(leaked)}, which served only the "
        "Cloudflare tunnel subsystem removed in plan v3.2. Nothing imports it."
    )


def test_nothing_in_the_product_imports_the_tunnel_sdk():
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(?:%s)\b" % "|".join(REMOVED_TUNNEL_MODULES),
        re.MULTILINE,
    )
    offenders = []
    for root in PRODUCT_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"tunnel SDK imported by: {offenders}"
