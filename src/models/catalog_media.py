
from __future__ import annotations

import re
from typing import Literal

from pydantic import field_validator

from .catalog_doc import _Doc

MEDIA_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class CardMedia(_Doc):

    sha256: str
    w: int
    h: int
    type: Literal["image/webp"]
    bytes: int
    source: Literal["generated", "author"]

    @field_validator("sha256")
    @classmethod
    def _sha_shape(cls, value: str) -> str:
        if not MEDIA_SHA_RE.match(value):
            raise ValueError("media sha256 is not 64 lowercase hex")
        return value
