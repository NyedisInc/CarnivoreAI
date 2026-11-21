
from __future__ import annotations


class PackInputError(ValueError):

    def __init__(self, detail: str, code: str = "bad_request") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
