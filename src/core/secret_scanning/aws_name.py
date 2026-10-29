
from __future__ import annotations

from typing import Match, Tuple

NAME_MARGIN: int = 64
KEYWORDS: Tuple[str, ...] = ("secret", "access")
DELIMITER_SLACK: int = 8
_WINDOW: int = 3 + NAME_MARGIN + max(map(len, KEYWORDS)) + NAME_MARGIN + DELIMITER_SLACK


def aws_name_ok(name: str, redaction: bool = False) -> bool:
    slack = min(DELIMITER_SLACK, len(name) - len(name.rstrip(".-"))) if redaction else 0
    tail = name[-_WINDOW:].lower()
    for word in KEYWORDS:
        at = tail.find(word)
        while at != -1:
            after = len(tail) - at - len(word)
            if after <= NAME_MARGIN + slack and "aws" in tail[max(0, at - 3 - NAME_MARGIN):at]:
                return True
            at = tail.find(word, at + 1)
    return False


def accept(match: Match[str]) -> bool:
    return aws_name_ok(match.group("name"))


def redact_accept(match: Match[str]) -> bool:
    return aws_name_ok(match.group("name"), redaction=True)
