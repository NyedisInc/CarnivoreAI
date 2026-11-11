
from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.notifications import catalog_lines, card_contract

CLIENT_ONLY = frozenset({"open", "later", "save", "play", "open_file", "save_file"})


@functools.lru_cache(maxsize=1)
def strings() -> Mapping[str, str]:
    return catalog_lines.read_prefixed(("notify.card.", "native.notify."))


def say(key: str, **values: Any) -> str:
    text = strings().get(key, key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def clock(ts: float) -> str:
    t = time.localtime(ts)
    return f"{t.tm_hour}:{t.tm_min:02d}"


def clip(text: Any, limit: int) -> str:
    return str(text or "")[:limit]


def clip_lines(text: Any, lines: int, width: int) -> List[str]:
    return [clip(ln, width) for ln in str(text or "").splitlines() if ln.strip()][:lines]


def fit_card(card: Dict[str, Any], limit: int = card_contract.LIMITS["card_bytes"]) -> Dict[str, Any]:
    out = dict(card)
    for _ in range(40):
        if len(card_contract.encode(out)) <= limit:
            break
        sizes = {k: len(card_contract.encode(v)) for k, v in out.items() if k not in ("strip", "opts") and isinstance(v, (str, list))}
        if not sizes:
            break
        key = max(sizes, key=sizes.get)  # type: ignore[arg-type]
        value = out[key]
        if isinstance(value, list) and len(value) > 1:
            out[key] = value[:-1]
        elif isinstance(value, str) and len(value) > 20:
            out[key] = value[: len(value) // 2]
        else:
            break
    return out


@dataclass
class Ctx:

    event: Any
    dialog: Optional[Dict[str, Any]]
    hint: Dict[str, Any]
    agent: str
    computer: str
    detail: bool
    kind: str = ""


@dataclass
class Part:

    card: Dict[str, Any] = field(default_factory=dict)
    full: Dict[str, Any] = field(default_factory=dict)
    acts: List[Tuple[str, str]] = field(default_factory=list)
    target: Optional[Dict[str, Any]] = None
    ask: bool = False
    media: Optional[Dict[str, Any]] = None


@dataclass
class Built:

    kind: str
    type_id: str
    title: str
    body: str
    sub: str
    path: str
    thread: str
    card: Dict[str, Any]
    full: Dict[str, Any]
    acts: List[Tuple[str, str]]
    target: Optional[Dict[str, Any]]
    ask: bool
    media: Optional[Dict[str, Any]]
    session_id: str = ""
    fingerprint: str = ""
    item: str = ""

    @property
    def needs_cap(self) -> bool:
        return self.media is not None or any(a not in CLIENT_ONLY for a, _ in self.acts)
