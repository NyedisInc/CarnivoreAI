
from __future__ import annotations

import unicodedata
from typing import Any, Callable, List, Optional, Tuple

MAX_MARKS = 3
MAX_LINES = 60
MAX_BLANK_RUN = 2
SPACE = " "
ZWNJ, ZWJ, VS16, KEYCAP = "\u200c", "\u200d", "\ufe0f", "\u20e3"
KEYCAP_BASES = frozenset("0123456789#*")
JOINING_SCRIPTS = frozenset({"ARABIC", "SYRIAC", "NKO", "MONGOLIAN", "MANDAIC", "ADLAM"})
VIRAMA_CLASS = 9
IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F),
    (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
    (0x2800, 0x2800), (0x1D159, 0x1D159),
    (0x16FE4, 0x16FE4), (0x1BC9D, 0x1BC9D), (0x2D7F, 0x2D7F), (0x1107F, 0x1107F), (0x113D0, 0x113D0), (0x11A47, 0x11A47), (0x11A99, 0x11A99),
    (0x11F42, 0x11F42),
    (0xFFFC, 0xFFFC), (0x13441, 0x13442), (0x1DA7F, 0x1DA80),
)
PICTOGRAPHIC = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122), (0x2139, 0x2139), (0x2194, 0x21AA),
    (0x231A, 0x23FF), (0x24C2, 0x24C2), (0x25AA, 0x25FE), (0x2600, 0x27BF), (0x2934, 0x2935), (0x2B05, 0x2B55), (0x3030, 0x3030),
    (0x303D, 0x303D), (0x3297, 0x3299), (0x1F000, 0x1FAFF),
)
SKIN_TONES = range(0x1F3FB, 0x1F400)
class TextRefused(ValueError):
    pass


def _in(c: str, ranges: tuple) -> bool:
    code = ord(c)
    return any(low <= code <= high for low, high in ranges)


def is_ignorable(c: str) -> bool:
    return _in(c, IGNORABLE)


def is_pictograph(c: str) -> bool:
    return _in(c, PICTOGRAPHIC)


def normalize(text: str) -> str:
    return "".join(SPACE if unicodedata.category(c) == "Zs" and not is_ignorable(c) else c for c in text)


def _script(c: Optional[str]) -> Optional[str]:
    if c is None or unicodedata.category(c)[0] != "L":
        return None
    return unicodedata.name(c, "").split(" ", 1)[0] or None


def _joiner_ok(text: str, i: int) -> bool:
    before = text[i - 1] if i > 0 else None
    after = text[i + 1] if i + 1 < len(text) else None
    if before is not None and unicodedata.combining(before) == VIRAMA_CLASS:
        return True
    script = _script(before)
    if text[i] == ZWNJ and script in JOINING_SCRIPTS and script == _script(after):
        return True
    if text[i] != ZWJ or after is None or not is_pictograph(after):
        return False
    j = i - 1
    if j >= 0 and (text[j] == VS16 or ord(text[j]) in SKIN_TONES):
        j -= 1
    return j >= 0 and is_pictograph(text[j])


def _vs16_ok(text: str, i: int) -> bool:
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    return bool(before) and (is_pictograph(before) or (before in KEYCAP_BASES and after == KEYCAP))


def visible(text: str, keep: str = "", *, private_use: bool = False) -> List[bool]:
    out: List[bool] = []
    marks = -1
    for i, c in enumerate(text):
        category = unicodedata.category(c)
        if c == VS16:
            ok, marks = _vs16_ok(text, i), -1
        elif c in (ZWJ, ZWNJ):
            ok, marks = _joiner_ok(text, i), -1
        elif is_ignorable(c):
            ok, marks = False, -1
        elif c == KEYCAP:
            ok, marks = i > 0 and (text[i - 1] in KEYCAP_BASES or (text[i - 1] == VS16 and i > 1 and text[i - 2] in KEYCAP_BASES)), -1
        elif category[0] == "M":
            ok = 0 <= marks < MAX_MARKS
            marks = marks + 1 if ok else -1
        elif category[0] in "LN":
            ok, marks = True, 0
        elif category[0] in "PS" or c == SPACE or (private_use and category == "Co"):
            ok, marks = True, -1
        else:
            ok, marks = c in keep, -1
        out.append(ok)
    return out


def keep_visible(text: str, keep: str = "", *, private_use: bool = False) -> str:
    while True:
        verdict = visible(text, keep, private_use=private_use)
        if all(verdict):
            return text
        text = "".join(c for c, ok in zip(text, verdict) if ok)


def lines_ok(text: str) -> bool:
    lines = text.split("\n")
    if len(lines) > MAX_LINES:
        return False
    run = 0
    for line in lines:
        run = run + 1 if not line.strip() else 0
        if run > MAX_BLANK_RUN:
            return False
    return True


def _dotted(path: Tuple[Any, ...]) -> str:
    return ".".join(str(step) for step in path)


def clean_json(value: Any, clean: Callable[[str], str], keep_as_sent: Optional[Callable[[Tuple[Any, ...], Any], bool]] = None) -> Any:
    root: List[Any] = [None]
    stack: List[Tuple[Any, Tuple[Any, ...], Any, Any]] = [(value, (), root, 0)]
    while stack:
        node, path, parent, slot = stack.pop()
        if keep_as_sent is not None and path and keep_as_sent(path, node):
            parent[slot] = node
        elif isinstance(node, str):
            parent[slot] = _clean_one(clean, node, path)
        elif isinstance(node, list):
            parent[slot] = copy = [None] * len(node)
            stack.extend((item, path + (at,), copy, at) for at, item in enumerate(node))
        elif isinstance(node, dict):
            parent[slot] = out = {}
            for key, item in node.items():
                clean_key = _clean_one(clean, key, path + (key,)) if isinstance(key, str) else key
                if clean_key in out:
                    raise TextRefused(f"{_dotted(path + (key,))}: keys collide once cleaned")
                out[clean_key] = None
                stack.append((item, path + (key,), out, clean_key))
        else:
            parent[slot] = node
    return root[0]


def _clean_one(clean: Callable[[str], str], text: str, path: Tuple[Any, ...]) -> str:
    try:
        return clean(text)
    except TextRefused as exc:
        where = _dotted(path)
        raise TextRefused(f"{where} {exc}" if where else str(exc)) from exc
