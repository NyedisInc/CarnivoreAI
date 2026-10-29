from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)


def strip_comments(text: str) -> str:
    return _COMMENTS.sub("", text)


def css_of(path: Path) -> str:
    if path.suffix not in {".css", ".svelte"}:
        return ""
    text = path.read_text()
    if path.suffix == ".svelte":
        text = "".join(_STYLE.findall(text))
    return strip_comments(text)


def top_level_chunks(css: str) -> list[str]:
    chunks: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunks.append(css[start:i + 1].strip())
                start = i + 1
    return chunks


ON_SCALE = re.compile(
    r"(?:padding|margin|gap)[\w-]*\s*:[^;}]*?(?<![\w.#-])(?:4|8|12|16|24|32)px\b"
    r"|font-size\s*:\s*(?:10|11|12)px\b"
)
ANY_PX = re.compile(r"(?:padding|margin|gap)[\w-]*\s*:[^;}]*?\d+(?:\.\d+)?px|font-size\s*:\s*\d+px")
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")


def unlayered_rules(css: str) -> int:
    return sum(1 for c in top_level_chunks(css) if not c.startswith("@layer"))


def on_scale_literals(css: str) -> int:
    return len(ON_SCALE.findall(css))
