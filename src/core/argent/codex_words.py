
from __future__ import annotations

import re
import shlex
from typing import Mapping, Tuple

BASE_ENV, AUTH_ENV = "CARNIVORE_GATEWAY_CODEX_BASE", "CARNIVORE_GATEWAY_CODEX_AUTH"
BASE_DELIVERY, AUTH_DELIVERY = "CARNIVORE_ARGENT_CODEX_BASE", "CARNIVORE_ARGENT_CODEX_AUTH"
_EXPAND = re.compile(r"\$\{(" + BASE_ENV + "|" + AUTH_ENV + r")\}")


def quote_word(word: str) -> str:
    parts = _EXPAND.split(word)
    return "".join('"${' + p + '}"' if n % 2 else shlex.quote(p) if p else "" for n, p in enumerate(parts)) or "''"


def expand_words(words: Tuple[str, ...], environ: Mapping[str, str]) -> list:
    return [_EXPAND.sub(lambda m: environ.get(m.group(1), ""), w) for w in words]
