
from __future__ import annotations

from typing import Dict, List, Tuple

from src.cplugs.sdk.sandboxed_html import VIEW_CSP

PERMISSIONS_POLICY = ", ".join(f"{name}=()" for name in (
    "accelerometer", "autoplay", "bluetooth", "camera", "clipboard-read", "clipboard-write", "display-capture", "fullscreen",
    "geolocation", "gyroscope", "hid", "magnetometer", "microphone", "midi", "payment", "screen-wake-lock", "serial", "usb",
    "xr-spatial-tracking"))

BASE_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
}

SHELL_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
             "frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
LOCKED_CSP = "default-src 'none'; frame-ancestors 'none'"
NO_STORE = "no-store"


def shell_headers() -> Dict[str, str]:
    return {**BASE_HEADERS, "Content-Security-Policy": SHELL_CSP}


def frame_headers() -> Dict[str, str]:
    return {**BASE_HEADERS, "Content-Security-Policy": VIEW_CSP, "Cache-Control": NO_STORE}


def api_headers() -> Dict[str, str]:
    return {**BASE_HEADERS, "Content-Security-Policy": LOCKED_CSP, "Cache-Control": NO_STORE}


def as_asgi(headers: Dict[str, str]) -> List[Tuple[bytes, bytes]]:
    return [(name.lower().encode("ascii"), value.encode("ascii")) for name, value in headers.items()]
