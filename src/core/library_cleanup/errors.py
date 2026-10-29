from __future__ import annotations


class CleanupError(Exception):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class CleanupNotFound(CleanupError):
    pass


class CleanupRefused(CleanupError):
    pass
