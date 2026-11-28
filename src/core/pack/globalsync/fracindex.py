
from __future__ import annotations

from typing import Optional


class FracindexError(ValueError):
    pass


ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
ZERO = ALPHABET[0]
MAX_KEY_LEN = 48


def _mid(a: str, b: Optional[str]) -> str:
    if b is not None:
        n = 0
        while (a[n] if n < len(a) else ZERO) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _mid(a[n:], b[n:])
    digit_a = ALPHABET.index(a[0]) if a else 0
    digit_b = ALPHABET.index(b[0]) if b is not None else BASE
    if digit_b - digit_a > 1:
        return ALPHABET[(digit_a + digit_b + 1) // 2]
    if b is not None and len(b) > 1:
        return b[:1]
    return ALPHABET[digit_a] + _mid(a[1:], None)


def key_between(a: Optional[str], b: Optional[str]) -> str:
    for key in (a, b):
        if key is not None and (not key or key.endswith(ZERO) or any(c not in ALPHABET for c in key)):
            raise FracindexError("position out of grammar")
    if a is not None and b is not None and a >= b:
        raise FracindexError("a must sort before b")
    return _mid(a or "", b)


def seed(i: int, n: int) -> str:
    if n < 1 or not 0 <= i < n:
        raise FracindexError("index out of range")
    width = 1
    while BASE ** width < 4 * (n + 1):
        width += 1
    value = (i + 1) * (BASE ** width) // (n + 1)
    digits = []
    for _ in range(width):
        value, rem = divmod(value, BASE)
        digits.append(ALPHABET[rem])
    key = "".join(reversed(digits))
    return key + ALPHABET[BASE // 2] if key.endswith(ZERO) else key


def needs_rebalance(key: str) -> bool:
    return len(key) > MAX_KEY_LEN
