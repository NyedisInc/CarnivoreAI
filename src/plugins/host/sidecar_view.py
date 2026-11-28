
from __future__ import annotations

from bisect import bisect_right
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.plugins.host import identity, runtime
from src.plugins.host.preview_check import MEDIA_TYPES, PreviewError, read_icon, read_preview, read_screenshot
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.host.sidecar_routes import _error, held_down, held_off, tier0_held_down
from src.plugins.sdk import signed_links
from src.plugins.sdk.manifest import ID_PATTERN
from src.plugins.sdk.manifest_v2 import VIEW_TYPES
from src.security_headers import OWN_POLICY_HEADER, build_view_csp

logger = structlog.get_logger()

TICKET_LABEL = "cplug-view-v1"
TICKET_TTL_S = 3600
MAX_FILE_BYTES = 2 * 1024 * 1024
VIEWS_FOLDER = "views"
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$")
_DOCUMENT_DESTS = frozenset({"document", "iframe", "frame", "embed", "object"})
FRAME_CSS_NAME = "carnivore-frame.css"
_FRAME_CSS_PATH = Path(__file__).with_name("carnivore_frame.css")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOKENS_CSS_PATH = _REPO_ROOT / "web" / "src" / "opscenter" / "tokens.css"
_DIST_CSS_PATH = _REPO_ROOT / "client" / "dist" / "app.css"
_FRAME_LINK_TAG = '<link rel="stylesheet" href="carnivore-frame.css">'
_FRAME_LINK_RE = re.compile(r"""<link\b[^>]*\bhref\s*=\s*["'][^"']*carnivore-frame\.css(?:\?[^"']*)?["']""", re.IGNORECASE)
_HEAD_OPEN_RE = re.compile(r"(<head(?:\s[^>]*)?>)", re.IGNORECASE)
_HTML_OPEN_RE = re.compile(r"(<html(?:\s[^>]*)?>)", re.IGNORECASE)
_ROOT_SELECTOR_RE = re.compile(r"^:root(?:\s*,\s*\[data-session-theme\])?$", re.S)
_THEME_SELECTOR_RE = re.compile(r"""^:root\[data-theme=(["'][^"']+["'])\]""")
_OC_DECL_RE = re.compile(r"(--oc-[a-z0-9-]+)\s*:\s*([^;]+?)\s*(?:;|$)")
_FRAME_CSS_CACHE_LOCK = threading.Lock()
_FRAME_CSS_CACHE: Optional[Tuple[Tuple[Any, ...], bytes]] = None

router = APIRouter(dependencies=[Depends(require_auth)], tags=["cplugs"])
public_router = APIRouter(tags=["cplugs"])


def _view_of(request: Request, cplug_id: str, name: str) -> Tuple[Any, dict, str]:
    host = runtime.host_for(request.app)
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    views = getattr(getattr(d, "manifest", None), "views", ()) or () if d is not None else ()
    view = next((v for v in views if isinstance(v, dict) and v.get("name") == name), None)
    if view is None or (isinstance(d, SidecarDefinition) and runtime.hidden(d)):
        raise _error(404, "cplug_unknown", "no such view")
    if not host.enabled(cplug_id):
        raise _error(409, "cplug_disabled", f"turn {cplug_id} on first")
    if isinstance(d, SidecarDefinition):
        live = host.sidecar_runtime()
        if live is None:
            raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
        if getattr(d.manifest, "tier0", False):
            if tier0_held_down(host, d, live):
                raise held_off(host, d, live)
        elif held_down(live, cplug_id):
            raise held_off(host, d, live)
        try:
            return d, view, host.install_key(cplug_id)
        except identity.LedgerUnreadable as exc:
            raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc
    if getattr(d, "code_root", None) is None:
        raise _error(404, "cplug_unknown", "no such view")
    return d, view, f"builtin:{d.id}"


def _strip_css_comments(text: str) -> str:
    out: List[str] = []
    n = len(text)
    pos = 0
    while pos < n:
        start = text.find("/*", pos)
        if start == -1:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        end = text.find("*/", start + 2)
        if end == -1:
            break
        pos = end + 2
    return "".join(out)


def _extract_oc_token_prelude(css_text: str) -> str:
    clean = _strip_css_comments(css_text)
    root_vars: Dict[str, str] = {}
    theme_vars: Dict[str, Dict[str, str]] = {}
    i, n, depth = 0, len(clean), 0
    while i < n:
        ch = clean[i]
        if ch == "{":
            depth += 1
            i += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            i += 1
        elif depth == 0:
            brace = clean.find("{", i)
            if brace == -1:
                break
            sel = clean[i:brace].split(";")[-1].strip()
            d, j = 1, brace + 1
            while j < n and d > 0:
                if clean[j] == "{":
                    d += 1
                elif clean[j] == "}":
                    d -= 1
                j += 1
            body = clean[brace + 1 : j - 1] if d == 0 else clean[brace + 1 :]
            if sel and not sel.startswith("@"):
                if _ROOT_SELECTOR_RE.match(sel):
                    for m in _OC_DECL_RE.finditer(body):
                        root_vars[m.group(1)] = " ".join(m.group(2).split())
                else:
                    tm = _THEME_SELECTOR_RE.match(sel)
                    if tm is not None:
                        bucket = theme_vars.setdefault(tm.group(1), {})
                        for m in _OC_DECL_RE.finditer(body):
                            bucket[m.group(1)] = " ".join(m.group(2).split())
            i = j
        else:
            i += 1
    if not root_vars and not theme_vars:
        return ""
    blocks: List[str] = []
    if root_vars:
        lines = [f"    {name}: {value};" for name, value in root_vars.items()]
        blocks.append(":root {\n" + "\n".join(lines) + "\n}")
    for theme_attr, decls in theme_vars.items():
        if decls:
            lines = [f"    {name}: {value};" for name, value in decls.items()]
            blocks.append(f":root[data-theme={theme_attr}] {{\n" + "\n".join(lines) + "\n}")
    return "\n\n".join(blocks) + "\n\n"


def _token_source_path() -> Optional[Path]:
    if _TOKENS_CSS_PATH.is_file():
        return _TOKENS_CSS_PATH
    if _DIST_CSS_PATH.is_file():
        return _DIST_CSS_PATH
    return None


def _read_frame_css() -> bytes:
    global _FRAME_CSS_CACHE
    frame_path = _FRAME_CSS_PATH
    tok_path = _token_source_path()
    try:
        frame_st = frame_path.stat()
        frame_key = (str(frame_path), frame_st.st_mtime_ns, frame_st.st_size)
    except OSError:
        frame_key = (str(frame_path), -1, -1)
    if tok_path is not None:
        try:
            tok_st = tok_path.stat()
            tok_key = (str(tok_path), tok_st.st_mtime_ns, tok_st.st_size)
        except OSError:
            tok_key = (str(tok_path), -1, -1)
    else:
        tok_key = ("", -1, -1)
    cache_key = frame_key + tok_key
    with _FRAME_CSS_CACHE_LOCK:
        if _FRAME_CSS_CACHE is not None and _FRAME_CSS_CACHE[0] == cache_key:
            return _FRAME_CSS_CACHE[1]
    frame_bytes = frame_path.read_bytes()
    prelude = ""
    if tok_path is not None:
        try:
            prelude = _extract_oc_token_prelude(tok_path.read_text(encoding="utf-8"))
        except OSError:
            prelude = ""
    combined = prelude.encode("utf-8") + frame_bytes if prelude else frame_bytes
    with _FRAME_CSS_CACHE_LOCK:
        _FRAME_CSS_CACHE = (cache_key, combined)
    return combined


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _ignored_html_spans(text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    lower = text.translate(_ASCII_LOWER)
    n = len(text)
    pos = 0
    while pos < n:
        lt = text.find("<", pos)
        if lt == -1:
            break
        if text.startswith("<!--", lt):
            end = text.find("-->", lt + 4)
            span_end = n if end == -1 else end + 3
            spans.append((lt, span_end))
            pos = span_end
            continue
        tag: Optional[str] = None
        if lower.startswith("<script", lt):
            tag = "script"
        elif lower.startswith("<style", lt):
            tag = "style"
        if tag is not None:
            tag_len = len(tag) + 1
            nxt = text[lt + tag_len : lt + tag_len + 1]
            if nxt == "" or nxt.isspace() or nxt in (">", "/"):
                gt = text.find(">", lt + tag_len)
                if gt == -1:
                    spans.append((lt, n))
                    break
                close_needle = f"</{tag}"
                close_pos = gt + 1
                span_end = n
                while True:
                    found = lower.find(close_needle, close_pos)
                    if found == -1:
                        break
                    after_idx = found + len(close_needle)
                    after = text[after_idx : after_idx + 1]
                    if after == "" or after.isspace() or after == ">":
                        gt_close = text.find(">", after_idx)
                        span_end = n if gt_close == -1 else gt_close + 1
                        break
                    close_pos = after_idx
                spans.append((lt, span_end))
                pos = span_end
                continue
        pos = lt + 1
    return spans


def _strip_ignored_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    if not spans:
        return text
    parts: List[str] = []
    cur = 0
    for start, end in spans:
        if start > cur:
            parts.append(text[cur:start])
        cur = end
    if cur < len(text):
        parts.append(text[cur:])
    return "".join(parts)


def _in_spans(pos: int, starts: List[int], spans: List[Tuple[int, int]]) -> bool:
    idx = bisect_right(starts, pos) - 1
    return idx >= 0 and spans[idx][0] <= pos < spans[idx][1]


def _insert_after_first_tag(
    text: str,
    tag_re: re.Pattern[str],
    insert: str,
    spans: Optional[List[Tuple[int, int]]] = None,
) -> Optional[str]:
    ignored = _ignored_html_spans(text) if spans is None else spans
    starts = [s for s, _ in ignored]
    for match in tag_re.finditer(text):
        if _in_spans(match.start(), starts, ignored):
            continue
        return f"{text[:match.end()]}{insert}{text[match.end():]}"
    return None


def _inject_frame_css(body: bytes) -> bytes:
    text = body.decode("utf-8", errors="replace")
    spans = _ignored_html_spans(text)
    stripped = _strip_ignored_spans(text, spans)
    if _FRAME_LINK_RE.search(stripped):
        return body
    injected = _insert_after_first_tag(text, _HEAD_OPEN_RE, _FRAME_LINK_TAG, spans)
    if injected is None:
        injected = _insert_after_first_tag(text, _HTML_OPEN_RE, f"<head>{_FRAME_LINK_TAG}</head>", spans)
    if injected is None:
        injected = f"{_FRAME_LINK_TAG}\n{text}"
    return injected.encode("utf-8")


def _file(code_root: Path, name: str, view: dict, rel: str) -> Optional[bytes]:
    rel = rel or "index.html"
    if rel not in view["files"]:
        return None
    top = Path(code_root) / VIEWS_FOLDER / name
    node = top
    try:
        for part in rel.split("/"):
            node = node / part
            if node.is_symlink():
                return None
        if top.is_symlink() or not node.resolve().is_relative_to(top.resolve()):
            return None
        if not stat.S_ISREG(os.lstat(node).st_mode):
            return None
        fd = os.open(node, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
                return None
            return fh.read(MAX_FILE_BYTES + 1)[:MAX_FILE_BYTES]
    except OSError:
        return None


@router.get("/cplugs/{cplug_id}/preview")
async def preview_image(cplug_id: str) -> Response:
    """The plugin's declared preview image, re-checked on every read. Output: the bytes, a fixed image type from the sniffed format, ``nosniff``.

    Description: shown as the drawer thumbnail and the plugins page card, so it answers while the plugin is off too. The file is the manifest's ``preview``
      only (a path from the digest-pinned code root, no symlink, 512 KiB at most, hero header rules). Raises: 404 ``cplug_unknown`` (not a sidecar, hidden, none declared, or the file no longer passes).
    """
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or not d.manifest.preview:
        raise _error(404, "cplug_unknown", "no preview")
    try:
        kind, body = await run_in_threadpool(read_preview, d.code_root, d.manifest.preview)
    except PreviewError as exc:
        logger.warning("cplug_preview_refused", cplug=cplug_id, reason=str(exc)[:120])
        raise _error(404, "cplug_unknown", "no preview") from exc
    return Response(content=body, media_type=MEDIA_TYPES[kind], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"})


@router.get("/cplugs/{cplug_id}/screenshots/{index}")
async def screenshot_image(cplug_id: str, index: int) -> Response:
    """One bundled screenshot (1-based index 1..4) from a plugin's code root, header-checked on read (#3404)."""
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d):
        raise _error(404, "cplug_unknown", "no screenshot")
    shots = tuple(getattr(d.manifest, "screenshots", ()) or ()) or ((d.manifest.preview,) if d.manifest.preview else ())
    if index < 1 or index > len(shots):
        raise _error(404, "cplug_unknown", "no screenshot")
    try:
        kind, body = await run_in_threadpool(read_screenshot, d.code_root, shots[index - 1])
    except PreviewError as exc:
        logger.warning("cplug_screenshot_refused", cplug=cplug_id, index=index, reason=str(exc)[:120])
        raise _error(404, "cplug_unknown", "no screenshot") from exc
    return Response(content=body, media_type=MEDIA_TYPES[kind], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"})


@router.get("/cplugs/{cplug_id}/icon")
async def custom_icon_image(cplug_id: str) -> Response:
    """Custom bundled PNG/WebP icon from a plugin's code root, header-checked on read (#3406)."""
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or not getattr(d.manifest, "icon_file", ""):
        raise _error(404, "cplug_unknown", "no custom icon")
    try:
        kind, body = await run_in_threadpool(read_icon, d.code_root, d.manifest.icon_file)
    except PreviewError as exc:
        logger.warning("cplug_icon_refused", cplug=cplug_id, reason=str(exc)[:120])
        raise _error(404, "cplug_unknown", "no custom icon") from exc
    return Response(content=body, media_type=MEDIA_TYPES[kind], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"})


@router.post("/cplugs/{cplug_id}/view/{name}/ticket")
async def view_ticket(cplug_id: str, name: str, request: Request) -> dict:
    """The path a frame loads for one view. Output: ``{path, expires_in}``; ``path`` is relative to the app origin and valid for an hour.

    Raises: 404 ``cplug_unknown``; 409 ``cplug_disabled``; 503. The page puts it in ``<iframe sandbox="allow-scripts" src>``.
    """
    d, _view, key = _view_of(request, cplug_id, name) if _NAME.match(name) else (None, None, "")
    if d is None:
        raise _error(404, "cplug_unknown", "no such view")
    ticket = signed_links.mint(TICKET_LABEL, [key, name], TICKET_TTL_S)
    return {"path": f"/api/v1/cplugs/{cplug_id}/view/{name}/{ticket}/index.html", "expires_in": TICKET_TTL_S}


@public_router.get("/cplugs/{cplug_id}/view/{name}/{ticket}/{rest:path}")
async def view_file(cplug_id: str, name: str, ticket: str, rest: str, request: Request) -> Response:
    """One declared file of a view, under the view's own policy. The ticket in the path is the credential (no bearer; an iframe cannot send one).

    Output: the file with its fixed content type, ``nosniff``, ``no-store`` and ``Content-Security-Policy`` from ``build_view_csp``.
    Raises: 404 (a bad or expired ticket, an undeclared view or file, a svg loaded as a page); 409 ``cplug_disabled``.
    """
    fields = signed_links.verify(TICKET_LABEL, ticket, 2) if _NAME.match(name) else None
    if fields is None or fields[1] != name:
        raise _error(404, "cplug_unknown", "no such view")
    d, view, key = _view_of(request, cplug_id, name)
    if fields[0] != key:
        raise _error(404, "cplug_unknown", "no such view file")
    netloc = request.url.netloc
    if not _HOST.match(netloc):
        raise HTTPException(status_code=400, detail={"code": "bad_host", "detail": "the Host header is not usable"})
    base = f"{request.url.scheme}://{netloc}/api/v1/cplugs/{cplug_id}/view/{name}/{ticket}/"
    headers = {
        "Content-Security-Policy": build_view_csp(base),
        OWN_POLICY_HEADER: "1",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if rest == FRAME_CSS_NAME:
        css_bytes = await run_in_threadpool(_read_frame_css)
        return Response(content=css_bytes, media_type="text/css", headers=headers)
    ext = (rest or "index.html").rsplit(".", 1)[-1]
    if ext not in VIEW_TYPES or (ext == "svg" and request.headers.get("sec-fetch-dest", "") in _DOCUMENT_DESTS):
        raise _error(404, "cplug_unknown", "no such view file")
    body = await run_in_threadpool(_file, d.code_root, name, view, rest)
    if body is None:
        raise _error(404, "cplug_unknown", "no such view file")
    if ext == "html":
        body = _inject_frame_css(body)
    return Response(content=body, media_type=VIEW_TYPES[ext], headers=headers)
