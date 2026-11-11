
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import structlog

from src.core.message_model_secrets import scan_text
from src.core.notify_media import store

logger = structlog.get_logger()

URL_MAX = 2000
TITLE_MAX = 120
NAME_MAX = 120
SCAN_MAX_BYTES = 2**20
HEAD_LINES = 8
HEAD_BYTES = 600
_TOOL_TIMEOUT = 15
_FTYP_VIDEO = {b"isom": "video/mp4", b"iso2": "video/mp4", b"mp41": "video/mp4", b"mp42": "video/mp4", b"avc1": "video/mp4",
               b"M4V ": "video/mp4", b"qt  ": "video/quicktime"}
_FTYP_HEIC = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"}
_EXT = {"video/mp4": ".mp4", "video/quicktime": ".mov", "application/pdf": ".pdf"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class IntakeError(Exception):

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def sniff(head: bytes) -> Tuple[str, str]:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _FTYP_HEIC:
            return "image", "image/heic"
        if brand in _FTYP_VIDEO:
            return "video", _FTYP_VIDEO[brand]
    if head[4:8] in (b"moov", b"mdat", b"wide", b"free"):
        return "video", "video/quicktime"
    if head.startswith(b"%PDF-"):
        return "file", "application/pdf"
    return "file", "application/octet-stream"


def _clean(value: Any, limit: int, what: str) -> str:
    if not isinstance(value, str) or _CTRL.search(value):
        raise IntakeError(422, f"bad_attachment: {what} must be plain text")
    value = value.strip()
    if len(value) > limit:
        raise IntakeError(422, f"bad_attachment: {what} is {len(value)} characters; the limit is {limit}")
    return value


def _link(url: Any, title: Any) -> Dict[str, Any]:
    url = _clean(url, URL_MAX, "url")
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or not parts.hostname or any(ch.isspace() for ch in url):
        raise IntakeError(422, "bad_url: the link must be a plain https url")
    hint: Dict[str, Any] = {"url": url}
    if title is not None and str(title).strip():
        hint["title"] = _clean(title, TITLE_MAX, "title")
    return hint


def _inside(real: str, roots: Sequence[str]) -> bool:
    for root in roots:
        base = os.path.realpath(root)
        if real == base or real.startswith(base.rstrip(os.sep) + os.sep):
            return True
    return False


def _open_regular(real: str, roots: Sequence[str]) -> int:
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise IntakeError(422, "bad_attachment: the file cannot be opened") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise IntakeError(422, "bad_attachment: the path is not a regular file")
        import fcntl

        if hasattr(fcntl, "F_GETPATH"):
            now = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0].decode("utf-8", "replace")
            if not _inside(os.path.realpath(now), roots):
                raise IntakeError(422, "outside_project: the file moved outside the project")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_capped(fd: int) -> Tuple[bytes, str, str]:
    size = os.fstat(fd).st_size
    head = os.pread(fd, 16, 0)
    kind, mime = sniff(head)
    cap = store.MAX_BYTES[kind]
    if size > cap:
        raise IntakeError(413, f"too_large: a {kind} may be at most {cap // 2**20} MB")
    chunks: List[bytes] = []
    got = 0
    while got <= cap:
        block = os.read(fd, min(1 << 20, cap + 1 - got))
        if not block:
            break
        chunks.append(block)
        got += len(block)
    data = b"".join(chunks)
    if len(data) > cap:
        raise IntakeError(413, f"too_large: a {kind} may be at most {cap // 2**20} MB")
    if not data:
        raise IntakeError(422, "bad_attachment: the file is empty")
    return data, kind, mime


def _scannable_text(data: bytes, kind: str) -> Optional[str]:
    if kind != "file" or len(data) > SCAN_MAX_BYTES or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _refuse_secrets(text: Optional[str]) -> None:
    found = scan_text(text) if text is not None else []
    if found:
        logger.info("agent_attachment_secret_refused", detector=found[0].detector)
        raise IntakeError(422, f"secret_found: the file looks like it holds a credential ({found[0].detector}); it was not sent")


def first_lines(text: str) -> List[str]:
    out: List[str] = []
    used = 0
    for raw in text.split("\n"):
        line = _CTRL.sub("", raw.rstrip())
        if not line.strip():
            continue
        room = HEAD_BYTES - used
        if len(out) == HEAD_LINES or room <= 0:
            break
        line = line.encode("utf-8")[:room].decode("utf-8", errors="ignore")
        out.append(line)
        used += len(line.encode("utf-8")) + 1
    return out


_PAGES_DICT = re.compile(rb"<<[^<>]*?/Type\s*/Pages\b[^<>]*?>>", re.S)
_COUNT = re.compile(rb"/Count\s+(\d{1,6})\b")


def pdf_pages(data: bytes) -> Optional[int]:
    counts = [int(m.group(1)) for d in _PAGES_DICT.finditer(data) for m in _COUNT.finditer(d.group(0))]
    return max(counts) if counts and max(counts) > 0 else None


def _run(cmd: List[str]) -> Optional[str]:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=_TOOL_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _poster_and_size(data: bytes, kind: str, mime: str) -> Tuple[Optional[bytes], Optional[int], Optional[int]]:
    if kind == "file" and mime != "application/pdf":
        return None, None, None
    work = tempfile.mkdtemp(prefix="cc_notify_media_")
    try:
        os.chmod(work, 0o700)
        src = Path(work) / ("media" + _EXT.get(mime, ""))
        fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if kind == "image":
            out = _run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)]) or ""
            w, h = (re.search(rf"{k}: (\d+)", out) for k in ("pixelWidth", "pixelHeight"))
            return None, int(w.group(1)) if w else None, int(h.group(1)) if h else None
        _run(["qlmanage", "-t", "-s", "640", "-o", work, str(src)])
        png = Path(work) / (src.name + ".png")
        if png.is_file() and 0 < png.stat().st_size <= store.MAX_POSTER_BYTES:
            return png.read_bytes(), None, None
        return None, None, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def prune_at_boot() -> None:
    try:
        store.prune()
    except OSError as exc:
        logger.warning("agent_attachment_prune_failed", error_type=type(exc).__name__)


def intake(attachment: Any, roots: Sequence[str], caption: str = "") -> Dict[str, Any]:
    if not isinstance(attachment, dict) or set(attachment) - {"path", "url", "title"} or ("path" in attachment) == ("url" in attachment):
        raise IntakeError(422, "bad_attachment: give exactly one of path or url (plus an optional title)")
    if "url" in attachment:
        return _link(attachment["url"], attachment.get("title"))
    raw = _clean(attachment["path"], 4096, "path")
    if not os.path.isabs(raw):
        raise IntakeError(422, "bad_attachment: path must be absolute")
    real = os.path.realpath(raw)
    if not _inside(real, [r for r in roots if r]):
        raise IntakeError(422, "outside_project: the file is not inside this session's project")
    fd = _open_regular(real, roots)
    try:
        data, kind, mime = _read_capped(fd)
    finally:
        os.close(fd)
    text = _scannable_text(data, kind)
    _refuse_secrets(text)
    poster, width, height = _poster_and_size(data, kind, mime)
    try:
        store.prune()
        entry = store.write(kind, data, mime, poster=poster)
    except (ValueError, OSError) as exc:
        raise IntakeError(422, "bad_attachment: the file could not be stored") from exc
    media: Dict[str, Any] = {"id": entry.media_id, "kind": kind, "name": _CTRL.sub("", os.path.basename(real))[:NAME_MAX],
                             "mime": mime, "bytes": entry.size}
    if width and height:
        media.update(w=width, h=height)
    if caption and kind != "file":
        media["caption"] = caption[:TITLE_MAX]
    if entry.poster is not None:
        media["poster"] = True
    pages = pdf_pages(data) if mime == "application/pdf" else None
    if pages:
        media["pages"] = pages
    lines = first_lines(text) if text is not None and mime != "application/pdf" else []
    if lines:
        media["head"] = lines
    return {"media": media}
