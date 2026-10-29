
from __future__ import annotations

from typing import Dict, Tuple

POSTURES = ("harness_default", "ask", "accept_edits", "skip_all")

PERMISSION_FLAGS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "claude": {
        "harness_default": (),
        "ask": ("--permission-mode", "manual"),
        "accept_edits": ("--permission-mode", "acceptEdits"),
        "skip_all": ("--dangerously-skip-permissions",),
    },
    "codex": {
        "harness_default": (),
        "ask": ("--ask-for-approval", "on-request"),
        "skip_all": ("--yolo",),
    },
    "shell": {"harness_default": ()},
}


class UnsupportedPosture(ValueError):

    def __init__(self, harness: str, posture: str) -> None:
        super().__init__(f"{harness} has no {posture} permissions posture")
        self.harness = harness
        self.posture = posture


def permission_flags(harness: str, posture: str) -> Tuple[str, ...]:
    try:
        return PERMISSION_FLAGS[harness][posture]
    except KeyError:
        raise UnsupportedPosture(harness, posture) from None
