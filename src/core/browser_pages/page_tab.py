
from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit

from src.security_headers import SELF_FRAMEABLE_PATHS

FRAME_SANDBOXED = "sandboxed"
FRAME_APP = "app"
KIND_ARTIFACT = "huddle_artifact"
DEFAULT_APP_TITLE = "carnivore"


class AppPageRefused(ValueError):
    pass


def is_app_path(url: str) -> bool:
    text = url.strip()
    return text.startswith("/") and not text.startswith("//")


def _page(key: str, src: str, frame: str) -> Dict[str, str]:
    return {"key": key, "src": src, "frame": frame}


def app_page(url: str) -> Dict[str, str]:
    text = url.strip()
    if not is_app_path(text) or "\\" in text or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise AppPageRefused("not a plain path on this server")
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or parts.path not in SELF_FRAMEABLE_PATHS:
        raise AppPageRefused(f"only {', '.join(sorted(SELF_FRAMEABLE_PATHS))} can open as a page; a self-contained "
                             "HTML page (flow_get html=true) is posted with task_manager_artifact_add and opened with this tool's huddle_artifact argument")
    src = urlunsplit(("", "", parts.path, parts.query, parts.fragment))
    return _page(f"app:{src}", src, FRAME_APP)


def app_title(src: str) -> str:
    tab: Optional[list] = parse_qs(urlsplit(src).query).get("tab")
    return (tab[0].strip() if tab and tab[0].strip() else DEFAULT_APP_TITLE)


def artifact_page(path: str, item: int, artifact: str) -> Dict[str, str]:
    return _page(f"{KIND_ARTIFACT}:{int(item)}:{artifact}", path, FRAME_SANDBOXED)


__all__ = ["AppPageRefused", "DEFAULT_APP_TITLE", "FRAME_APP", "FRAME_SANDBOXED", "KIND_ARTIFACT", "app_page", "app_title",
           "artifact_page", "is_app_path"]
