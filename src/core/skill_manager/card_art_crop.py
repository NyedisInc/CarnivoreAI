
from __future__ import annotations

from src.core.media.image_ops import crop_16_9_png

REQUEST_SIZE = "1536x864"
RATIO_W, RATIO_H = 16, 9


def crop_16_9(raw: bytes) -> bytes:
    return crop_16_9_png(raw)
