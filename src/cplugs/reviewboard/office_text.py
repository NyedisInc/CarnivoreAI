
from __future__ import annotations

import codecs
import io
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

import structlog

from src.cplugs.reviewboard.office_xml import SizeExceeded, extract
from src.cplugs.sdk.file_secrets import Deadline, ScanTimeout

logger = structlog.get_logger()

MAX_MEMBERS = 2000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_RAW_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
MIN_RATIO_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 16 * 1024 * 1024
MAX_DEPTH = 4

REASON_CORRUPT = "corrupt_archive"
REASON_ENCRYPTED = "encrypted"
REASON_TOO_MANY = "too_many_entries"
REASON_TOO_BIG = "too_much_data"
REASON_BAD_NAME = "unsafe_entry_name"
REASON_DUPLICATE = "duplicate_entry"
REASON_DTD = "dtd_in_part"
REASON_METHOD = "unsupported_compression"
REASON_NESTED = "nested_too_deep"
REASON_RATIO = "compression_ratio"
REASON_TIMEOUT = "scan_timeout"

_OLE_MAGIC = b"\xd0\xcf\x11\xe0"
_HEAD_BYTES = 16
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_MEDIA_PREFIXES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\x00", b"MM\x00*", b"wOFF", b"wOF2", b"OTTO", b"\x00\x01\x00\x00", b"true")
_ALLOWED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_ASCII_RUN = re.compile(rb"[\x20-\x7e]{8,}")
_UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){8,}")
_BOMS = {codecs.BOM_UTF32_LE: "utf-32", codecs.BOM_UTF32_BE: "utf-32", codecs.BOM_UTF16_LE: "utf-16", codecs.BOM_UTF16_BE: "utf-16",
         codecs.BOM_UTF8: "utf-8-sig"}
_BARE = ((b"<\x00\x00\x00", "utf-32-le"), (b"\x00\x00\x00<", "utf-32-be"), (b"<\x00", "utf-16-le"), (b"\x00<", "utf-16-be"))


class OfficeUnreadable(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Scan:

    joined: List[str] = field(default_factory=list)
    separated: List[str] = field(default_factory=list)
    raw_left: int = field(default_factory=lambda: MAX_RAW_BYTES)
    raw_used: int = 0
    compressed_used: int = 0
    deadline: Optional[Deadline] = None
    text_left: int = field(default_factory=lambda: MAX_TEXT_CHARS)
    members_left: int = field(default_factory=lambda: MAX_MEMBERS)


def _decode(raw: bytes) -> str:
    for bom, codec in _BOMS.items():
        if raw.startswith(bom):
            return raw.decode(codec, errors="replace")
    for prefix, codec in _BARE:
        if raw.startswith(prefix):
            return raw.decode(codec, errors="replace")
    return raw.decode("utf-8", errors="replace")


def _printable_runs(raw: bytes) -> str:
    runs = [m.group().decode("ascii") for m in _ASCII_RUN.finditer(raw)]
    runs += [m.group().decode("utf-16-le") for m in _UTF16_RUN.finditer(raw)]
    return "\n".join(runs)


def _check_members(infos: List[zipfile.ZipInfo], scan: _Scan) -> None:
    scan.members_left -= len(infos)
    if scan.members_left < 0:
        raise OfficeUnreadable(REASON_TOO_MANY)
    seen: Set[str] = set()
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in name.split("/") or "\x00" in name:
            raise OfficeUnreadable(REASON_BAD_NAME)
        if name in seen:
            raise OfficeUnreadable(REASON_DUPLICATE)
        seen.add(name)
        if info.flag_bits & 0x1:
            raise OfficeUnreadable(REASON_ENCRYPTED)
        if info.compress_type not in _ALLOWED_METHODS:
            raise OfficeUnreadable(REASON_METHOD)


def _is_media(head: bytes) -> bool:
    return head.startswith(_MEDIA_PREFIXES) or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")


def _is_markup(head: bytes) -> bool:
    if head.startswith(tuple(_BOMS)) or head.startswith(tuple(prefix for prefix, _ in _BARE)):
        return True
    return head.removeprefix(codecs.BOM_UTF8).lstrip(b" \t\r\n").startswith(b"<")


def _read_into(fh: "zipfile.ZipExtFile", head: bytes, size: int) -> bytearray:
    buf = bytearray(max(size, len(head)))
    buf[:len(head)] = head
    view, filled = memoryview(buf), len(head)
    while filled < len(buf):
        got = fh.readinto(view[filled:])
        if not got:
            break
        filled += got
    view.release()
    del buf[filled:]
    return buf


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, scan: _Scan) -> Optional[bytearray]:
    with archive.open(info) as fh:
        head = fh.read(_HEAD_BYTES)
        if _is_media(head):
            return None
        hard = min(MAX_PART_BYTES, scan.raw_left)
        ratio_cap = max(MIN_RATIO_BYTES, MAX_RATIO * info.compress_size)
        limit, reason = (ratio_cap, REASON_RATIO) if ratio_cap < hard else (hard, REASON_TOO_BIG)
        if info.file_size > limit:
            raise OfficeUnreadable(reason)
        raw = _read_into(fh, head, info.file_size)
    scan.raw_left -= len(raw)
    scan.raw_used += len(raw)
    scan.compressed_used += info.compress_size
    if scan.raw_used > MAX_RATIO * scan.compressed_used + MIN_RATIO_BYTES:
        raise OfficeUnreadable(REASON_RATIO)
    return raw


def _keep(scan: _Scan, joined: str, separated: str) -> None:
    scan.text_left -= max(len(joined), len(separated))
    if scan.text_left < 0:
        raise OfficeUnreadable(REASON_TOO_BIG)
    scan.joined.append(joined)
    if separated:
        scan.separated.append(separated)


def _read_markup(box: List[bytearray], scan: _Scan) -> None:
    xml = _decode(box.pop())
    if "<!ENTITY" in xml:
        raise OfficeUnreadable(REASON_DTD)
    try:
        readings = extract(xml, limit=scan.text_left, deadline=scan.deadline)
    except SizeExceeded as exc:
        raise OfficeUnreadable(REASON_TOO_BIG) from exc
    _keep(scan, readings.joined, readings.separated)


def _read_binary(raw: bytes, scan: _Scan, depth: int) -> None:
    text = _printable_runs(raw)
    _keep(scan, text, "")
    start = raw.find(_ZIP_SIGNATURES[0]) if raw.startswith(_OLE_MAGIC) and depth < MAX_DEPTH else -1
    if start > 0:
        try:
            inner = zipfile.ZipFile(io.BytesIO(raw[start:]))
        except zipfile.BadZipFile:
            return
        with inner:
            _walk(inner, scan, depth + 1)


def _read_part(archive: zipfile.ZipFile, info: zipfile.ZipInfo, scan: _Scan, depth: int) -> None:
    if scan.deadline is not None:
        scan.deadline.check()
    raw = _read_entry(archive, info, scan)
    if raw is None:
        return
    if raw.startswith(_ZIP_SIGNATURES):
        if depth >= MAX_DEPTH:
            raise OfficeUnreadable(REASON_NESTED)
        with zipfile.ZipFile(io.BytesIO(raw)) as inner:
            _walk(inner, scan, depth + 1)
    elif _is_markup(raw[:_HEAD_BYTES]):
        box = [raw]
        del raw
        _read_markup(box, scan)
    else:
        _read_binary(raw, scan, depth)


def _walk(archive: zipfile.ZipFile, scan: _Scan, depth: int) -> None:
    infos = archive.infolist()
    _check_members(infos, scan)
    for info in infos:
        _read_part(archive, info, scan, depth)


def office_texts(data: bytes, deadline: Optional[Deadline] = None) -> Tuple[str, str]:
    scan = _Scan(deadline=deadline)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _walk(archive, scan, 0)
    except OfficeUnreadable:
        raise
    except ScanTimeout as exc:
        logger.warning("reviewboard_office_scan_timeout")
        raise OfficeUnreadable(REASON_TIMEOUT) from exc
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        logger.info("reviewboard_office_unreadable", error=type(exc).__name__)
        raise OfficeUnreadable(REASON_ENCRYPTED if isinstance(exc, RuntimeError) else REASON_CORRUPT) from exc
    return "\n".join(scan.joined), "\n".join(scan.separated)
