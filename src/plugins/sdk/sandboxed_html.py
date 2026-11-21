
from __future__ import annotations

import re
from typing import Dict

VIEW_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data:; font-src data:; media-src data:; connect-src 'none'; frame-src 'none'; worker-src 'none'; "
            "object-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")

_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def view_headers(filename: str) -> Dict[str, str]:
    if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
        raise ValueError(f"viewer file name {filename!r} must be 1 to 64 plain characters")
    return {"Content-Security-Policy": VIEW_CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="{filename}"'}
