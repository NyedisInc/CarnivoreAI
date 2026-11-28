
from __future__ import annotations

import gzip
import hashlib
import posixpath
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs

import structlog
from starlette.datastructures import Headers
from starlette.responses import Response

from src.core import static_asset_keys

_logger = structlog.get_logger()

BUNDLE_MOUNT_PREFIX = "_bundle/"

BUNDLE_URL_PREFIX = static_asset_keys.STATIC_PREFIX + BUNDLE_MOUNT_PREFIX

_CSS_TAG_RE = re.compile(
    r"""<link\s+rel=["']stylesheet["']\s+href=["'](/static/(?:css|vendor/xterm|dist)/[^"'?]+\.css)["']\s*/?>""",
    re.IGNORECASE,
)

_JS_TAG_RE = re.compile(
    r"""<script\s+src=["'](/static/(?:js|vendor/xterm)/[^"'?]+\.js)["']\s*></script>""",
    re.IGNORECASE,
)

_BETWEEN_RE = re.compile(r"""^(?:\s|<!--[\s\S]*?-->)*$""")

_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^)'"]+)\1\s*\)""", re.IGNORECASE)

_SOURCE_MAP_RE = re.compile(
    r"""(?:^|\n)[ \t]*(?://[#@][ \t]*sourceMappingURL=.*|/\*[#@][ \t]*sourceMappingURL=.*?\*/)[ \t]*(?=\n|$)"""
)

_LOCK = threading.Lock()


@dataclass(frozen=True)
class _BundleEntry:

    name: str
    kind: str
    media_type: str
    members: Tuple[Tuple[str, Path], ...]
    stat_stamp: Tuple[Tuple[int, int], ...]
    key: str
    raw: bytes
    gzipped: bytes


_BUNDLES: Dict[Tuple[str, str], _BundleEntry] = {}


def _stat_members(members: Sequence[Tuple[str, Path]]) -> Optional[Tuple[Tuple[int, int], ...]]:
    stamps: List[Tuple[int, int]] = []
    for _, path in members:
        try:
            st = path.stat()
        except OSError:
            return None
        stamps.append((st.st_size, st.st_mtime_ns))
    return tuple(stamps)


def _rewrite_css_urls(css_text: str, member_url: str) -> str:
    base_dir = posixpath.dirname(member_url)

    def _sub(match: re.Match[str]) -> str:
        quote, raw_target = match.group(1), match.group(2).strip()
        lower = raw_target.lower()
        if (
            not raw_target
            or raw_target.startswith(("/", "#"))
            or lower.startswith(("data:", "http:", "https:", "blob:"))
        ):
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(base_dir, raw_target))
        if not resolved.startswith("/"):
            resolved = "/" + resolved
        return f"url({quote}{resolved}{quote})"

    return _CSS_URL_RE.sub(_sub, css_text)


def _css_braces_balanced(css_text: str) -> bool:
    depth = 0
    i = 0
    n = len(css_text)
    while i < n:
        ch = css_text[i]
        if ch == "/" and css_text.startswith("/*", i):
            end = css_text.find("*/", i + 2)
            if end < 0:
                return False
            i = end + 2
            continue
        if ch in "\"'":
            i += 1
            while i < n and css_text[i] != ch:
                if css_text[i] == "\\":
                    i += 1
                elif css_text[i] == "\n":
                    return False
                i += 1
            if i >= n:
                return False
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _assemble_bundle(
    name: str,
    kind: str,
    members: Tuple[Tuple[str, Path], ...],
    stat_stamp: Tuple[Tuple[int, int], ...],
) -> Optional[_BundleEntry]:
    parts: List[str] = []
    try:
        for url, path in members:
            text = path.read_text(encoding="utf-8")
            text = _SOURCE_MAP_RE.sub("", text)
            if kind == "css":
                if not _css_braces_balanced(text):
                    _logger.warning("shell_bundle_member_unbalanced", member=url, bundle=name)
                    return None
                text = _rewrite_css_urls(text, url)
            parts.append(text)
    except (OSError, UnicodeDecodeError):
        return None
    separator = "\n" if kind == "css" else "\n;\n"
    raw = separator.join(parts).encode("utf-8")
    key = hashlib.sha256(raw).hexdigest()[: static_asset_keys.KEY_LENGTH]
    gzipped = gzip.compress(raw, compresslevel=6)
    media_type = "text/css; charset=utf-8" if kind == "css" else "application/javascript; charset=utf-8"
    return _BundleEntry(
        name=name,
        kind=kind,
        media_type=media_type,
        members=members,
        stat_stamp=stat_stamp,
        key=key,
        raw=raw,
        gzipped=gzipped,
    )


def _get_or_build(
    client_dir: Path,
    name: str,
    kind: str,
    members: Tuple[Tuple[str, Path], ...],
) -> Optional[_BundleEntry]:
    stat_stamp = _stat_members(members)
    if stat_stamp is None:
        return None
    cache_key = (str(client_dir.resolve()), name)
    with _LOCK:
        cached = _BUNDLES.get(cache_key)
        if cached is not None and cached.members == members and cached.stat_stamp == stat_stamp:
            return cached
    built = _assemble_bundle(name, kind, members, stat_stamp)
    if built is None:
        return None
    with _LOCK:
        _BUNDLES[cache_key] = built
    return built


def _bundle_runs(html: str, client_dir: Path, pattern: re.Pattern[str], kind: str) -> str:
    matches = list(pattern.finditer(html))
    if len(matches) < 2:
        return html
    runs: List[List[re.Match[str]]] = []
    current: List[re.Match[str]] = [matches[0]]
    for m in matches[1:]:
        gap = html[current[-1].end() : m.start()]
        if _BETWEEN_RE.match(gap):
            current.append(m)
        else:
            runs.append(current)
            current = [m]
    runs.append(current)

    out: List[str] = []
    cursor = 0
    bundle_idx = 0
    for run in runs:
        if len(run) < 2:
            continue
        members: List[Tuple[str, Path]] = []
        valid = True
        for m in run:
            url = m.group(1)
            resolved = static_asset_keys.url_to_path(url, client_dir)
            if resolved is None or not resolved.is_file():
                valid = False
                break
            members.append((url, resolved))
        if not valid:
            continue
        ext = "css" if kind == "css" else "js"
        name = f"{kind}-{bundle_idx}.{ext}"
        entry = _get_or_build(client_dir, name, kind, tuple(members))
        if entry is None:
            continue
        bundle_idx += 1
        out.append(html[cursor : run[0].start()])
        href = f"{BUNDLE_URL_PREFIX}{name}?v={entry.key}"
        if kind == "css":
            out.append(f'<link rel="stylesheet" href="{href}" />')
        else:
            out.append(f'<script src="{href}"></script>')
        cursor = run[-1].end()
    if cursor == 0:
        return html
    out.append(html[cursor:])
    return "".join(out)


def render_bundled_shell(html: str, client_dir: Path) -> str:
    html = _bundle_runs(html, client_dir, _CSS_TAG_RE, "css")
    html = _bundle_runs(html, client_dir, _JS_TAG_RE, "js")
    return html


def serve_bundle(path: str, scope: dict, client_dir: Path) -> Optional[Response]:
    if not path.startswith(BUNDLE_MOUNT_PREFIX):
        return None
    name = path[len(BUNDLE_MOUNT_PREFIX) :]
    if "/" in name or "\\" in name or not name:
        return None
    root_key = str(client_dir.resolve())
    with _LOCK:
        entry = _BUNDLES.get((root_key, name))
    if entry is None:
        return None
    fresh = _get_or_build(client_dir, entry.name, entry.kind, entry.members)
    if fresh is None:
        return None

    query = scope.get("query_string", b"")
    requested = parse_qs(query.decode("latin-1")).get("v", [""])[0] if b"v=" in query else ""
    cache_control = static_asset_keys.IMMUTABLE if requested == fresh.key else static_asset_keys.REVALIDATE
    etag = f'"{fresh.key}"'
    req_headers = Headers(scope=scope)
    if_none_match = req_headers.get("if-none-match", "")
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
        "Vary": "Accept-Encoding",
    }
    if if_none_match.strip() == etag:
        return Response(status_code=304, headers=headers)
    accept_encoding = req_headers.get("accept-encoding", "")
    if "gzip" in accept_encoding:
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(fresh.gzipped))
        return Response(content=fresh.gzipped, status_code=200, headers=headers, media_type=fresh.media_type)
    headers["Content-Length"] = str(len(fresh.raw))
    return Response(content=fresh.raw, status_code=200, headers=headers, media_type=fresh.media_type)


def warm(client_dir: Path, shell_path: Optional[Path] = None) -> int:
    target = shell_path or (client_dir / static_asset_keys.SHELL_NAME)
    try:
        html = target.read_text(encoding="utf-8")
    except OSError:
        return 0
    render_bundled_shell(html, client_dir)
    root_key = str(client_dir.resolve())
    with _LOCK:
        return sum(1 for (r, _) in _BUNDLES if r == root_key)


def reset_for_tests() -> None:
    with _LOCK:
        _BUNDLES.clear()
