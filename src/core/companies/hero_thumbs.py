
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from src.core.companies import hero_images
from src.core.media.image_ops import render_thumbnail

logger = structlog.get_logger()

TIERS = {"thumb": 128, "card": 1400, "banner": 2400}
THUMB_MAX_PX = TIERS["thumb"]
THUMBS_DIR = "thumbs"
THUMB_EXT = "avif"
_THUMB_QUALITY = 80
_CLEANUP_EXTS = ("avif", "webp")


def _thumb_path(kind: str, row_id: int, original: Path, tier: str) -> Optional[Path]:
    try:
        stat = original.stat()
    except OSError:
        return None
    return hero_images.images_dir(kind) / THUMBS_DIR / f"{int(row_id)}-{tier}-{stat.st_mtime_ns}-{stat.st_size}.{THUMB_EXT}"


def _render(original: Path, max_px: int) -> bytes:
    data, _ext, _mime = render_thumbnail(original, max_px, quality=_THUMB_QUALITY)
    return data


def thumb_for(kind: str, row_id: int, original: Path, tier: str = "thumb") -> Optional[Path]:
    target = _thumb_path(kind, row_id, original, tier)
    if target is None:
        return None
    if target.is_file():
        return target
    try:
        hero_images.atomic_write(target, _render(original, TIERS[tier]))
    except (OSError, ValueError) as exc:
        logger.warning("hero_thumb_failed", kind=kind, tier=tier, row_id=row_id, path=str(original), error=str(exc))
        return None
    stale_globs = [f"{int(row_id)}-{tier}-*.{ext}" for ext in _CLEANUP_EXTS]
    if tier == "thumb":
        stale_globs.extend(f"{int(row_id)}-[0-9]*.{ext}" for ext in _CLEANUP_EXTS)
    for pattern in stale_globs:
        for stale in target.parent.glob(pattern):
            if stale != target:
                stale.unlink(missing_ok=True)
    return target

