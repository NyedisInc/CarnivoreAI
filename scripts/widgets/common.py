from __future__ import annotations

import struct
import subprocess
from pathlib import Path
from typing import Any

DESKTOP_MIN_WIDTH_PX = 500
DESKTOP_HEIGHT_PX, PHONE_HEIGHT_PX = 1100, 844
STAGE_MARGIN_PX = 16
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_HEADER_LEN = 24
GIT_TIMEOUT_S = 30


def page_height(width: int) -> int:
    return DESKTOP_HEIGHT_PX if width > DESKTOP_MIN_WIDTH_PX else PHONE_HEIGHT_PX


def viewport_for(size: dict, mode: str) -> dict:
    if mode == "box" and size.get("h"):
        return {"width": size["w"] + 2 * STAGE_MARGIN_PX, "height": size["h"] + 2 * STAGE_MARGIN_PX}
    return {"width": size["viewport"], "height": page_height(size["viewport"])}


def key_slug(key: str) -> str:
    return key.replace(":", "--")


def key_matches(key: str, only: list[str]) -> bool:
    return not only or any(key == o or (o.endswith(":") and key.startswith(o)) for o in only)


def git_output(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


def source_revision(repo: Path) -> dict[str, Any]:
    return {"sha": git_output(repo, "rev-parse", "HEAD"),
            "dirty": bool(git_output(repo, "status", "--porcelain", "--", "web/src", "src", "client"))}


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(PNG_SIGNATURE) or len(data) < _PNG_HEADER_LEN:
        return None
    width, height = struct.unpack(">II", data[16:_PNG_HEADER_LEN])
    return width, height
