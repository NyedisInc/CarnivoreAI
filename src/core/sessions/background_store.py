
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional

import structlog

from src.core.terminal_background import (
    UnsafeImageName,
    clamp_dim,
    safe_image_filename,
)
from src.core.unique_tmp_path import unique_tmp_path

logger = structlog.get_logger()


def _coerce_entry(raw: object) -> Optional[Dict[str, object]]:
    if not isinstance(raw, dict):
        return None
    theme_id = raw.get("theme_id")
    if not isinstance(theme_id, str) or not theme_id:
        theme_id = None
    dim = raw.get("dim")
    dim = clamp_dim(dim) if isinstance(dim, (int, float)) and not isinstance(dim, bool) else None
    disabled = bool(raw.get("disabled"))
    # state directory
    image = raw.get("image")
    if isinstance(image, str) and image:
        try:
            image = safe_image_filename(image)
        except UnsafeImageName as exc:
            logger.warning(
                "session_background_image_name_refused", reason=exc.reason
            )
            image = None
    else:
        image = None
    if theme_id is None and dim is None and not disabled and image is None:
        return None
    return {
        "theme_id": theme_id,
        "dim": dim,
        "disabled": disabled,
        "image": image,
    }


class SessionBackgroundStore:

    def __init__(self, *, path: Callable[[], Path]) -> None:
        self._path = path
        self.overrides: Dict[str, Dict[str, object]] = {}

    def load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            with open(path, "r") as fh:
                raw = json.load(fh)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("failed_to_load_session_backgrounds", error=str(exc))
            return
        if not isinstance(raw, dict):
            logger.warning(
                "session_backgrounds_unexpected_shape", type=type(raw).__name__
            )
            return
        loaded: Dict[str, Dict[str, object]] = {}
        for name, value in raw.items():
            entry = _coerce_entry(value)
            if entry is not None:
                loaded[str(name)] = entry
        self.overrides = loaded
        logger.info("session_backgrounds_loaded", count=len(self.overrides))

    def save(self) -> None:
        path = self._path()
        tmp: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                try:
                    path.with_suffix(path.suffix + ".bak").write_bytes(
                        path.read_bytes()
                    )
                except OSError as exc:
                    logger.warning(
                        "session_backgrounds_backup_failed",
                        path=str(path),
                        error=str(exc),
                    )
            tmp = unique_tmp_path(path)
            with tmp.open("w") as fh:
                json.dump(self.overrides, fh, indent=2)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(str(tmp), str(path))
        except (OSError, TypeError, ValueError) as exc:
            logger.error("failed_to_save_session_backgrounds", error=str(exc))
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def get(self, tmux_name: str) -> Optional[Dict[str, object]]:
        return self.overrides.get(tmux_name)

    def set(
        self,
        tmux_name: str,
        *,
        theme_id: Optional[str],
        dim: Optional[float],
        disabled: bool,
    ) -> Optional[Dict[str, object]]:
        existing = self.overrides.get(tmux_name) or {}
        entry = _coerce_entry(
            {
                "theme_id": theme_id,
                "dim": dim,
                "disabled": disabled,
                "image": existing.get("image"),
            }
        )
        if entry is None:
            self.overrides.pop(tmux_name, None)
        else:
            self.overrides[tmux_name] = entry
        self.save()
        return entry

    def set_image(
        self, tmux_name: str, image: Optional[str]
    ) -> Optional[Dict[str, object]]:
        if image is not None:
            image = safe_image_filename(image)
        existing = self.overrides.get(tmux_name) or {}
        entry = _coerce_entry(
            {
                "theme_id": existing.get("theme_id"),
                "dim": existing.get("dim"),
                "disabled": existing.get("disabled"),
                "image": image,
            }
        )
        if entry is None:
            self.overrides.pop(tmux_name, None)
        else:
            self.overrides[tmux_name] = entry
        self.save()
        return entry
