
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

SHORT_N = 56


def short(text: str, n: int = SHORT_N) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("`", "")).strip()
    text = re.sub(r"^item \d+: ", "", text)
    parts = re.split(r"(?<=[.:!?]) ", text)
    while len(parts) > 1 and re.match(r"^(From |Sent to )", parts[0]):
        parts.pop(0)
    out = parts[0].rstrip(".:")
    for nxt in parts[1:]:
        if len(out) >= 24:
            break
        out += ". " + nxt.rstrip(".:")
    if len(out) > n:
        out = out[:n].rsplit(" ", 1)[0].rstrip(",;:-") + "..."
    return out


def clean_title(title: str) -> str:
    return re.sub(r"\s*\([^()]*\)\s*$", "", title or "").strip()


def display_name(label: str) -> str:
    name = re.sub(r"\s*\([^()]*\)\s*$", "", label or "").strip()
    name = re.sub(r"^Agent\s+-\s+", "", name)
    return name or label


def monogram(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)[:2]).upper() or "?"


def clock(t: float, tz: Optional[dt.tzinfo]) -> str:
    return dt.datetime.fromtimestamp(t, tz).strftime("%H:%M")
