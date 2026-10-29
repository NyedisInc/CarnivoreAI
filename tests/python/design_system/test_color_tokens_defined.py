
from __future__ import annotations

import re

from tests.python.design_system._sources import REPO

OPTIONAL_TOKENS: frozenset[str] = frozenset({"--color-badge-ended-bg"})
_READ = re.compile(r"var\(\s*(--color-[\w-]+)")
_DEFINE = re.compile(r"(--color-[\w-]+)\s*\"?\s*:")


def undefined_reads(read_texts: list[str], define_texts: list[str]) -> set[str]:
    defined = {m for text in define_texts for m in _DEFINE.findall(text)}
    read = {m for text in read_texts for m in _READ.findall(text)}
    return read - defined - OPTIONAL_TOKENS


def test_scanner_can_go_red() -> None:
    assert undefined_reads(["a { color: var(--color-nope, #fff); }"], [":root { --color-fg: #111; }"]) == {"--color-nope"}


def test_every_color_token_a_legacy_sheet_reads_is_defined() -> None:
    css = sorted((REPO / "client" / "css").rglob("*.css"))
    reads = [p.read_text() for p in css]
    manifests = [p.read_text() for p in (REPO / "client" / "css" / "themes").glob("*/theme.json")]
    assert css, "no stylesheets found"
    assert undefined_reads(reads, reads + manifests) == set()
