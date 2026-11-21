
from __future__ import annotations


class SideloadRefused(Exception):

    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.status = code, status

