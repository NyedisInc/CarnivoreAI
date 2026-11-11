
from __future__ import annotations

NAME = "huddle.owner_reply"


class OwnerReplyUnavailable(Exception):
    pass


class OwnerReplyDeclined(Exception):
    pass


class OwnerReplyRefused(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
