
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from src.cplugs.publicboard.headers import NO_STORE, shell_headers

PUBLIC_DIR = Path(__file__).with_name("public")
FILES: Dict[str, Tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}


@lru_cache(maxsize=None)
def asset_file(path: str) -> Tuple[str, bytes]:
    name, content_type = FILES[path]
    return content_type, (PUBLIC_DIR / name).read_bytes()


def asset_headers() -> Dict[str, str]:
    return {**shell_headers(), "Cache-Control": NO_STORE}
