
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from src.plugins.reviewboard.public.headers import NO_STORE, shell_headers

PUBLIC_DIR = Path(__file__).with_name("page")
DIST_DIR = Path(__file__).resolve().parents[4] / "client" / "dist"
FILES: Dict[str, Tuple[str, str, str]] = {
    "/": ("public", "index.html", "text/html; charset=utf-8"),
    "/publicboard.js": ("dist", "reviewboard-public.js", "text/javascript; charset=utf-8"),
    "/publicboard.css": ("dist", "reviewboard-public.css", "text/css; charset=utf-8"),
}


_CACHE: Dict[str, Tuple[Tuple[str, int, int], str, bytes]] = {}


def asset_file(path: str) -> Tuple[str, bytes]:
    where, name, content_type = FILES[path]
    file = (PUBLIC_DIR if where == "public" else DIST_DIR) / name
    stat = file.stat()
    stamp = (str(file), stat.st_mtime_ns, stat.st_size)
    hit = _CACHE.get(path)
    if hit is None or hit[0] != stamp:
        hit = (stamp, content_type, file.read_bytes())
        _CACHE[path] = hit
    return hit[1], hit[2]


def asset_headers() -> Dict[str, str]:
    return {**shell_headers(), "Cache-Control": NO_STORE}
