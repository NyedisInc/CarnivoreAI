
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import structlog
from PIL import Image, UnidentifiedImageError

from src.core.companies import hero_images

logger = structlog.get_logger()

TIERS = {"thumb": 128, "card": 1400, "banner": 2400}
THUMB_MAX_PX = TIERS["thumb"]
THUMBS_DIR = "thumbs"
_WEBP_QUALITY = 80


def _thumb_path(kind: str, row_id: int, original: Path, tier: str) -> Optional[Path]:
    try:
        stat = original.stat()
    except OSError:
        return None
    return hero_images.images_dir(kind) / THUMBS_DIR / f"{int(row_id)}-{tier}-{stat.st_mtime_ns}-{stat.st_size}.webp"


def _render(original: Path, max_px: int) -> bytes:
    with Image.open(original) as image:
        image.thumbnail((max_px, max_px))
        converted = image.convert("RGBA" if "A" in image.getbands() or image.mode == "P" else "RGB")
        out = io.BytesIO()
        converted.save(out, format="WEBP", quality=_WEBP_QUALITY)
        return out.getvalue()


def thumb_for(kind: str, row_id: int, original: Path, tier: str = "thumb") -> Optional[Path]:
    target = _thumb_path(kind, row_id, original, tier)
    if target is None:
        return None
    if target.is_file():
        return target
    try:
        hero_images.atomic_write(target, _render(original, TIERS[tier]))
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as exc:
        logger.warning("hero_thumb_failed", kind=kind, tier=tier, row_id=row_id, path=str(original), error=str(exc))
        return None
    stale_globs = [f"{int(row_id)}-{tier}-*.webp"] + ([f"{int(row_id)}-[0-9]*.webp"] if tier == "thumb" else [])
    for pattern in stale_globs:
        for stale in target.parent.glob(pattern):
            if stale != target:
                stale.unlink(missing_ok=True)
    return target

