
from __future__ import annotations


class ControlUnavailable(Exception):
    pass


class ControlStaleServer(ControlUnavailable):
    pass


class ControlPaneGone(Exception):
    pass


class ControlFallback(Exception):

    def __init__(self, remaining: bytes) -> None:
        super().__init__(f"{len(remaining)} bytes unapplied")
        self.remaining = remaining


class ControlWriteUnknown(RuntimeError):
    """Whether the bytes landed could not be measured; sending again could duplicate them."""
