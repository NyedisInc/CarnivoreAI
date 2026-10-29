
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Iterable, Optional

KEY_LENGTH = 12

STATIC_PREFIX = "/static/"

IMMUTABLE = "public, max-age=31536000, immutable"

REVALIDATE = "no-cache, must-revalidate"

_SRC_TAG = re.compile(r"""<[a-zA-Z][^>]*\bsrc\s*=\s*["'](/static/[^"']*)["']""")
_LINK_TAG = re.compile(
    r"""<link\b[^>]*\bhref\s*=\s*["'](/static/[^"']*)["']""", re.IGNORECASE
)

_LOCK = threading.Lock()

DEFAULT_CLIENT_DIR = Path(__file__).resolve().parent.parent.parent / "client"

SHELL_NAME = "index.html"

EXTRA_SHELL_NAMES: tuple[str, ...] = ("popout.html",)

KEYED_PAGE_NAMES: tuple[str, ...] = (*EXTRA_SHELL_NAMES, "style-guide.html", "setup.html")

_KEY_CACHE: dict[str, tuple[int, int, str]] = {}

_PATH_CACHE: dict[tuple[str, str], Optional[Path]] = {}


def content_key(path: Path) -> Optional[str]:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    stamp = (stat_result.st_size, stat_result.st_mtime_ns)
    cache_id = str(path)
    with _LOCK:
        cached = _KEY_CACHE.get(cache_id)
        if cached is not None and (cached[0], cached[1]) == stamp:
            return cached[2]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:KEY_LENGTH]
    except OSError:
        return None
    with _LOCK:
        _KEY_CACHE[cache_id] = (stamp[0], stamp[1], digest)
    return digest


def key_is_current(path: Path, key: str) -> bool:
    if not key:
        return False
    return content_key(path) == key


def cache_control_for(path: Optional[Path], requested_key: str) -> str:
    """Decide the Cache-Control header for one static hit.

    Args:
        path: the file being served, or None when the URL could not be
            resolved to one inside the static root.
        requested_key: the ``v=`` query value, ``""`` when absent.

    Returns:
        ``IMMUTABLE`` only for a resolvable file whose current content key
        equals ``requested_key``; ``REVALIDATE`` for everything else,
        every failure to determine included.

    Example:
        >>> cache_control_for(Path("client/js/app.js"), "wrongkey")
        'no-cache, must-revalidate'
    """
    if path is None or not key_is_current(path, requested_key):
        return REVALIDATE
    return IMMUTABLE


def url_to_path(url: str, client_dir: Path) -> Optional[Path]:
    if not url.startswith(STATIC_PREFIX):
        return None
    cache_id = (url, str(client_dir))
    with _LOCK:
        if cache_id in _PATH_CACHE:
            return _PATH_CACHE[cache_id]
    candidate = (client_dir / url[len(STATIC_PREFIX):]).resolve()
    try:
        candidate.relative_to(client_dir.resolve())
    except ValueError:
        candidate = None
    with _LOCK:
        _PATH_CACHE[cache_id] = candidate
    return candidate


def render(html: str, client_dir: Path) -> str:
    def rewrite(match: "re.Match[str]") -> str:
        """Key one matched tag, or hand it back untouched.

        Args:
            match: a ``_SRC_TAG`` or ``_LINK_TAG`` match, group 1 the URL.

        Returns:
            str: the tag with ``?v=<key>`` on its URL, or the original
            text whenever a key cannot be determined - which is the
            fail-soft direction, since an unkeyed URL still loads and
            still revalidates.
        """
        url = match.group(1)
        if "?" in url:
            return match.group(0)
        path = url_to_path(url, client_dir)
        if path is None:
            return match.group(0)
        key = content_key(path)
        if not key:
            return match.group(0)
        return match.group(0).replace(url, f"{url}?v={key}", 1)

    return _LINK_TAG.sub(rewrite, _SRC_TAG.sub(rewrite, html))


def shell_fingerprint(html: str) -> tuple[float, int]:
    digest = hashlib.sha256(html.encode("utf-8")).digest()
    return (float(int.from_bytes(digest[:6], "big")), len(html))


def iter_static_urls(html: str) -> Iterable[str]:
    found = [(m.start(), m.group(1)) for m in _SRC_TAG.finditer(html)]
    found += [(m.start(), m.group(1)) for m in _LINK_TAG.finditer(html)]
    for _, url in sorted(found):
        yield url


def warm(client_dir: Path, shell: Path) -> int:
    """Hash every asset the shell references, once, at import time.

    A cold pass reads and hashes each referenced file. That is real work
    and it must not land on the first user request, which is the same
    bargain - and the same remedy - as
    ``static_serving.warm_static_gzip_cache`` beside the call site.

    Args:
        client_dir: filesystem root the ``/static/`` prefix maps to.
        shell: the HTML template whose references should be pre-hashed.

    Returns:
        int: how many URLs were keyed, for the startup log line. ``0``
        when the shell could not be read, which is not an error here: it
        costs the optimisation only, the next request re-derives whatever
        it can, and a boot must never fail over a cache warm.
    """
    try:
        html = shell.read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for url in iter_static_urls(render(html, client_dir)) if "?v=" in url)


_SHELL_PATHS_CACHE: dict[str, tuple[int, int, tuple[Path, ...]]] = {}


def _shell_asset_paths(client_dir: Path, name: str = SHELL_NAME) -> tuple[Path, ...]:
    shell = client_dir / name
    try:
        stat_result = shell.stat()
    except OSError:
        return ()
    stamp = (stat_result.st_size, stat_result.st_mtime_ns)
    cache_id = f"{client_dir}|{name}"
    with _LOCK:
        cached = _SHELL_PATHS_CACHE.get(cache_id)
        if cached is not None and cached[:2] == stamp:
            return cached[2]
    try:
        html = shell.read_text(encoding="utf-8")
    except OSError:
        return ()
    paths = [shell]
    for url in iter_static_urls(html):
        path = url_to_path(url.split("?", 1)[0], client_dir)
        if path is not None:
            paths.append(path)
    result = tuple(paths)
    with _LOCK:
        _SHELL_PATHS_CACHE[cache_id] = (stamp[0], stamp[1], result)
    return result


def client_build_key(client_dir: Path = DEFAULT_CLIENT_DIR) -> str:
    paths = _shell_asset_paths(client_dir)
    if not paths:
        return ""
    for name in EXTRA_SHELL_NAMES:
        paths += tuple(p for p in _shell_asset_paths(client_dir, name) if p not in paths)
    folded = hashlib.sha256()
    for path in paths:
        folded.update((content_key(path) or "-").encode("ascii"))
        folded.update(b"\n")
    return folded.hexdigest()[:KEY_LENGTH]


def reset_for_tests() -> None:
    with _LOCK:
        _KEY_CACHE.clear()
        _PATH_CACHE.clear()
        _SHELL_PATHS_CACHE.clear()
