
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


def aws_secret_key() -> str:
    return synthetic_body(40)


def google_api_key() -> str:
    return "AI" + "za" + synthetic_body(35)


def slack_bot_token() -> str:
    digits = "56789"
    ids = ["".join(secrets.choice(digits) for _ in range(13)) for _ in range(2)]
    return "xo" + "xb-" + "-".join(ids) + "-" + synthetic_body(24)


def github_fine_grained_token() -> str:
    return "github" + "_pat_" + synthetic_body(22) + "_" + synthetic_body(59)
