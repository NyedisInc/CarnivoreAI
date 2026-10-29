
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

REQUEST_SIZE = "1536x864"
RATIO_W, RATIO_H = 16, 9


def crop_16_9(raw: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            im = src.convert("RGBA") if src.mode in ("RGBA", "LA", "P") else src.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"the image reply does not decode: {type(exc).__name__}") from exc
    w, h = im.size
    if w * RATIO_H == h * RATIO_W:
        return raw
    if w * RATIO_H > h * RATIO_W:
        new_w, new_h = h * RATIO_W // RATIO_H, h
    else:
        new_w, new_h = w, w * RATIO_H // RATIO_W
    left, top = (w - new_w) // 2, (h - new_h) // 2
    out = io.BytesIO()
    im.crop((left, top, left + new_w, top + new_h)).save(out, "PNG")
    return out.getvalue()
