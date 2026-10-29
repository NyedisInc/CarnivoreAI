
from __future__ import annotations

from urllib.parse import quote

ISSUER = "Carnivore"
_FALLBACK = "carnivore"
_MAX_CODE_POINTS = 64

_DROP_RANGES = (
    (0x0000, 0x001F), (0x007F, 0x009F), (0x00AD, 0x00AD), (0x200B, 0x200F),
    (0x202A, 0x202E), (0x2066, 0x2069), (0x2060, 0x2064), (0xFEFF, 0xFEFF),
    (0xD800, 0xDFFF),
)

_SPACE = frozenset(
    [0x0020, 0x00A0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000] + list(range(0x2000, 0x200B))
)


def _dropped(cp: int) -> bool:
    return cp == 0x3A or any(lo <= cp <= hi for lo, hi in _DROP_RANGES)


def sanitize_account(name: str) -> str:
    out: list[str] = []
    for ch in name:
        cp = ord(ch)
        if _dropped(cp):
            continue
        if cp in _SPACE:
            if out and out[-1] == " ":
                continue
            out.append(" ")
        else:
            out.append(ch)
    text = "".join(out).strip(" ")
    text = text[:_MAX_CODE_POINTS].rstrip(" ")
    return text or _FALLBACK


def build_otpauth_uri(secret: str, computer_name: str) -> str:
    issuer = quote(ISSUER, safe="")
    account = quote(sanitize_account(computer_name), safe="")
    return f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}"
