
from __future__ import annotations

import secrets

_SAFE_ALPHABET: str = "GHJKLQVWZgjkqvwz56789"

ANTHROPIC_PREFIXES: tuple = (
    "sk-" + "ant-api03-",
    "sk-" + "ant-admin01-",
    "sk-" + "ant-oat01-",
)
OPENAI_PREFIXES: tuple = (
    "sk-" + "proj-",
    "sk-" + "svcacct-",
    "sk-" + "admin-",
)


def synthetic_body(length: int, alphabet: str = _SAFE_ALPHABET) -> str:
    chars = ["G", "5"]
    while len(chars) < length:
        pick = secrets.choice(alphabet)
        if pick != chars[-1]:
            chars.append(pick)
    return "".join(chars[:length])


def anthropic_key(prefix: str = ANTHROPIC_PREFIXES[0]) -> str:
    return prefix + synthetic_body(93) + "AA"


def openai_key(prefix: str = OPENAI_PREFIXES[0]) -> str:
    return prefix + synthetic_body(74) + "T3Blbk" + "FJ" + synthetic_body(74)


def github_token() -> str:
    return "gh" + "p_" + synthetic_body(36)


def aws_key_id() -> str:
    return "AKI" + "A" + synthetic_body(16, "GHJKLQVWZ56789")
