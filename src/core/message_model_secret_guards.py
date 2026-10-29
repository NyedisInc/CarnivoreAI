
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Tuple

REFERENCE_PREFIXES: Tuple[str, ...] = ("op://", "vault://", "keychain://")

PLACEHOLDER_MARKERS: Tuple[str, ...] = (
    "placeholder", "your", "yours", "changeme", "change_me",
    "dummy", "sample", "redacted", "notreal", "fake", "test", "xxxx",
    "0000", "1234", "abcd", "deadbeef", "insert", "replace", "todo",
    "fixme", "somekey", "sometoken", "secretgoeshere", "goeshere",
)

DOCUMENTED_SAMPLE_VALUES: frozenset = frozenset({
    "AKIAIOSFODNN7EXAMPLE",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
})

_INDIRECTION_RE = re.compile(
    r"""(?ix)
    ^(?:
        \$\{?[A-Za-z_][A-Za-z0-9_]*\}?     # $VAR or ${VAR}
      | %[A-Za-z_][A-Za-z0-9_]*%           # %VAR% (windows)
      | os\.environ.*                      # python
      | process\.env.*                     # node
      | \{\{.*\}\}                         # template placeholder
      | <[^>]*>                            # <your-token-here>
      | \.\.\.+
    )$
    """
)

MAX_REPEATED_RUN: int = 4


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum(
        (n / total) * math.log2(n / total) for n in counts.values()
    )


def _is_reference(value: str) -> bool:
    return any(value.startswith(p) for p in REFERENCE_PREFIXES)


def _is_indirection(value: str) -> bool:
    return bool(_INDIRECTION_RE.match(value.strip()))


def _has_long_repeat(value: str) -> bool:
    run = 1
    for prev, char in zip(value, value[1:]):
        run = run + 1 if char == prev else 1
        if run > MAX_REPEATED_RUN:
            return True
    return False


def has_mixed_alphabet(value: str) -> bool:
    return any(c.isupper() for c in value) and any(c.isdigit() for c in value)


def is_placeholder(value: str) -> bool:
    if _is_reference(value) or _is_indirection(value):
        return True
    if value in DOCUMENTED_SAMPLE_VALUES:
        return True
    if _has_long_repeat(value):
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)
