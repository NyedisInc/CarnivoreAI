
from __future__ import annotations

import errno
import glob
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional

import structlog

from src.core.server_log import breadcrumb, locate

logger = structlog.get_logger()

MAX_TAIL_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MIN_TAIL_BYTES = 256
LEGACY_TMP_GLOB = "/tmp/carnivore-menubar*.log"
MAX_LEGACY_TMP_FILES = 4
MENUBAR_LOG_DIR_NAME = "Carnivore"
MENUBAR_LOG_NAMES = ("menubar.log", "menubar-error.log")
STARTUP_ERRORS_NAME = "startup-errors.log"
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_PRIVATE_KEY_END = re.compile(r"^-----END [A-Z ]*PRIVATE KEY-----", re.MULTILINE)

Redactor = Callable[[str], str]
Shorten = Callable[[str], str]


@dataclass(frozen=True)
class LogSpec:

    name: str
    path: Path
    source: str
    checked_open: bool = False


def _server_log_specs(mode: str, state_dir: Optional[Path]) -> List[LogSpec]:
    specs: List[LogSpec] = []
    if mode != "server" and state_dir is not None:
        try:
            located = breadcrumb.read_breadcrumb(state_dir)
            specs.append(LogSpec("server.log", located.path, f"breadcrumb:{located.status}", checked_open=True))
        except (breadcrumb.BreadcrumbError, OSError) as exc:
            logger.info("diagnostics_breadcrumb_unusable", error_type=type(exc).__name__,
                        reason=getattr(exc, "reason", None))
    specs.append(LogSpec("server.log", locate.server_log_path(), "launcher" if locate.own_log_path() else "default"))
    return specs


def _own_regular_files(candidates: List[str]) -> List[Path]:
    keep: List[Path] = []
    for raw in candidates:
        try:
            info = os.lstat(raw)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid():
            keep.append(Path(raw))
    return keep


def known_logs(mode: str, state_dir: Optional[Path]) -> List[LogSpec]:
    home = Path.home()
    menubar_logs = home / "Library" / "Logs" / MENUBAR_LOG_DIR_NAME
    specs = _server_log_specs(mode, state_dir)
    specs.append(LogSpec("server.log (app default)", locate.default_log_path(), "default"))
    specs.append(LogSpec("launchd.log", home / "Library" / "Logs" / locate.LAUNCHD_LOG_DIR_NAME / locate.LAUNCHD_LOG_FILE_NAME,
                          "launch agent"))
    specs.append(LogSpec(STARTUP_ERRORS_NAME, locate.default_log_path().parent / STARTUP_ERRORS_NAME, "app"))
    specs.extend(LogSpec(name, menubar_logs / name, "menubar") for name in MENUBAR_LOG_NAMES)
    for legacy in _own_regular_files(sorted(glob.glob(LEGACY_TMP_GLOB)))[:MAX_LEGACY_TMP_FILES]:
        specs.append(LogSpec(legacy.name, legacy, "menubar (legacy /tmp)"))
    seen: set = set()
    unique: List[LogSpec] = []
    for spec in specs:
        if spec.path not in seen:
            seen.add(spec.path)
            unique.append(spec)
    return unique


def _open_plain(path: Path) -> BinaryIO:
    return os.fdopen(os.open(path, _OPEN_FLAGS), "rb")


def read_tail(path: Path, limit: int, opener: Callable[[Path], BinaryIO] = _open_plain) -> Dict[str, Any]:
    blank: Dict[str, Any] = {"size_bytes": None, "truncated": False, "text": None}
    try:
        handle = opener(path)
    except FileNotFoundError:
        return {**blank, "status": "missing"}
    except breadcrumb.BreadcrumbRefused as exc:
        return {**blank, "status": "missing" if exc.reason.endswith("_missing") else "refused"}
    except OSError as exc:
        return {**blank, "status": "refused" if exc.errno == errno.ELOOP else "unreadable"}
    with handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            return {**blank, "status": "refused"}
        size = info.st_size
        start = max(0, size - limit)
        try:
            handle.seek(start)
            raw = handle.read(limit)
        except OSError as exc:
            logger.warning("diagnostics_log_read_failed", error_type=type(exc).__name__)
            return {**blank, "status": "unreadable", "size_bytes": size}
    text = raw.decode("utf-8", errors="replace")
    if start > 0:
        text = text.partition("\n")[2]
        end = _PRIVATE_KEY_END.search(text)
        if end is not None and "-----BEGIN" not in text[: end.start()]:
            text = text[end.end():].partition("\n")[2]
    return {"status": "ok", "size_bytes": size, "truncated": start > 0, "text": text}


def _fit(text: str, room: int) -> str:
    cost = len(json.dumps(text))
    while cost > room and text:
        keep = int(len(text) * room / cost * 0.95)
        text = text[len(text) - keep:].partition("\n")[2] if keep > 0 else ""
        cost = len(json.dumps(text))
    return text


def collect(
    mode: str,
    state_dir: Optional[Path],
    redact: Redactor,
    shorten: Shorten,
    *,
    specs: Optional[List[LogSpec]] = None,
    per_log: int = MAX_TAIL_BYTES,
    total: int = MAX_TOTAL_BYTES,
    min_tail: int = MIN_TAIL_BYTES,
) -> Dict[str, Any]:
    budget = total
    logs: List[Dict[str, Any]] = []
    for spec in specs if specs is not None else known_logs(mode, state_dir):
        entry: Dict[str, Any] = {"name": spec.name, "path": shorten(str(spec.path)), "source": spec.source}
        if budget < min_tail:
            logs.append({**entry, "status": "skipped_total_cap", "size_bytes": None, "truncated": False, "text": None})
            continue
        tail = read_tail(spec.path, min(per_log, budget),
                         breadcrumb.open_log_nofollow if spec.checked_open else _open_plain)
        if tail["text"] is not None:
            try:
                redacted = redact(shorten(tail["text"]))
            except Exception as exc:  # noqa: BLE001
                logger.error("diagnostics_log_redaction_failed", log=spec.name, error_type=type(exc).__name__)
                tail["text"], tail["status"] = None, "dropped_redaction_failed"
            else:
                fitted = _fit(redacted, budget)
                tail["truncated"] = tail["truncated"] or len(fitted) < len(redacted)
                tail["text"] = fitted
                budget -= len(json.dumps(fitted))
        logs.append({**entry, **tail})
    return {"cap_bytes_per_log": per_log, "cap_bytes_total": total, "logs": logs}
