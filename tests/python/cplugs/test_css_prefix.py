
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Counter as CounterT, Dict

import pytest

from src.cplugs.host import runtime

ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = {d.id: d for d in runtime.definitions()}
SHARED_FAMILIES = frozenset({"oc", "pl", "modal", "tw"})
MAX_FOREIGN_SHARE = 0.1
PREFIX_MISMATCH_OK = {"huddle": "css_prefix is hdr but the classes are hd and hb; the Task Manager split owner decides (#1711)"}

_COMMENT, _URL, _SELECTOR, _CLASS = re.compile(r"/\*.*?\*/", re.S), re.compile(r"url\([^)]*\)"), re.compile(r"([^{}]+)\{"), re.compile(r"\.([a-zA-Z_][\w-]*)")


def class_families(css: str) -> CounterT[str]:
    text = _URL.sub("", _COMMENT.sub("", css))
    found: CounterT[str] = Counter()
    for selector in _SELECTOR.findall(text):
        for name in _CLASS.findall(selector):
            found[re.split(r"[-_]", name)[0]] += 1
    return found


def families_of(plugin_id: str) -> Dict[str, int]:
    total: CounterT[str] = Counter()
    for sheet in sorted((ROOT / "web" / "src" / "cplugs" / plugin_id).glob("*.css")):
        total += class_families(sheet.read_text(encoding="utf-8"))
    return dict(total)


def foreign_share(prefix: str, families: Dict[str, int]) -> float:
    count = sum(families.values())
    outside = sum(n for f, n in families.items() if f != prefix and f not in SHARED_FAMILIES)
    return outside / count if count else 0.0


@pytest.mark.parametrize("pid", sorted(DEFINITIONS))
def test_a_plugins_stylesheets_use_its_declared_prefix(pid: str) -> None:
    families = families_of(pid)
    if not families:
        pytest.skip("no stylesheet")
    prefix = DEFINITIONS[pid].manifest.css_prefix
    share = foreign_share(prefix, families)
    if pid in PREFIX_MISMATCH_OK:
        assert share > MAX_FOREIGN_SHARE, f"{pid} now conforms: drop it from PREFIX_MISMATCH_OK"
        return
    assert share <= MAX_FOREIGN_SHARE, f"{pid}: css_prefix is {prefix!r} but its classes are {families}"


def test_the_prefix_check_can_fail() -> None:
    assert class_families(".rb-a{} .rb-b .oc-x{} .zz_y{}") == Counter({"rb": 2, "oc": 1, "zz": 1})
    assert foreign_share("rb", {"rb": 8, "oc": 3, "zz": 2}) == 2 / 13
    assert foreign_share("rb", {"hd": 5}) == 1.0 and foreign_share("rb", {}) == 0.0
    assert set(PREFIX_MISMATCH_OK) <= set(DEFINITIONS) and families_of("reviewboard")
    assert DEFINITIONS["reviewboard"].manifest.css_prefix == "rb"
