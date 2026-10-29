
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, NamedTuple, Optional, Set, Union

import structlog

from src.core.pipeline import contract as C

logger = structlog.get_logger()

BRCTL_BIN: str = "brctl"
DOWNLOAD_TIMEOUT_SECONDS: float = 30.0


class ReadTimeout(TimeoutError):
    pass


_helpers_lock = threading.Lock()
_helpers: Dict[str, threading.Thread] = {}
_downloading: Set[str] = set()


def hung_helpers() -> int:
    with _helpers_lock:
        return sum(1 for t in _helpers.values() if t.is_alive())


def timed(fn: Callable[..., Any], *args: Any, timeout: Optional[float] = None, key: Optional[str] = None) -> Any:
    box: Dict[str, Any] = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            done.set()
            if key is not None:
                with _helpers_lock:
                    if _helpers.get(key) is threading.current_thread():
                        del _helpers[key]

    helper = threading.Thread(target=run, name="pipeline-read", daemon=True)
    if key is not None:
        with _helpers_lock:
            earlier = _helpers.get(key)
            if earlier is not None and earlier.is_alive():
                raise ReadTimeout(f"an earlier read of {getattr(fn, '__name__', 'file')} is still hung")
            _helpers[key] = helper
    helper.start()
    if not done.wait(C.READ_TIMEOUT_SECONDS if timeout is None else timeout):
        raise ReadTimeout(f"read of {getattr(fn, '__name__', 'file')} timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def read_slice(path: str, start: int, size: int, limit: int) -> bytes:
    if size <= start:
        return b""
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read(min(limit, size - start))
        parts = [data]
        total = len(data)
        while b"\n" not in parts[-1] and start + total < size:
            more = handle.read(min(limit, size - start - total))
            if not more:
                break
            parts.append(more)
            total += len(more)
    data = b"".join(parts) if len(parts) > 1 else data
    cut = data.rfind(b"\n")
    return data[:cut + 1] if cut >= 0 else b""


class Check(NamedTuple):

    reset: Optional[str]
    checked_bytes: int


def check_cursor(path: str, size: int, offset: int, serial: Optional[str], serial_offset: Optional[int]) -> Check:
    from src.core.transcript_manifest.tail import line_serial

    if offset > size:
        return Check(C.EV_TRUNCATED, 0)
    if offset == 0:
        return Check(None, 0)
    if serial is None or serial_offset is None or not 0 <= serial_offset < offset:
        return Check(C.EV_FILE_REWRITTEN, 0)
    with open(Path(path), "rb") as handle:
        handle.seek(serial_offset)
        line = handle.read(offset - serial_offset)
    holds = len(line) == offset - serial_offset and line.endswith(b"\n") and line_serial(line[:-1]) == serial
    return Check(None if holds else C.EV_FILE_REWRITTEN, len(line))


def request_download(path: Union[str, Path]) -> bool:
    """Ask iCloud to download exactly one placeholder file, on its own thread. Never raises, never blocks.

    Output: True when a request was started, False when one for this path is already running.
    Inputs: path - the placeholder file. Example: request_download('/Users/x/.../agent-1.jsonl')
    """
    name = str(path)
    with _helpers_lock:
        if name in _downloading:
            return False
        _downloading.add(name)

    def run() -> None:
        try:
            _download(name)
        finally:
            with _helpers_lock:
                _downloading.discard(name)

    threading.Thread(target=run, name="pipeline-download", daemon=True).start()
    return True


def _download(path: str) -> bool:
    argv = [BRCTL_BIN, "download", path]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=DOWNLOAD_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("pipeline_icloud_download_timeout", path=path)
        return False
    except OSError as exc:  # not executable
        logger.warning("pipeline_icloud_download_unavailable", path=path, error=str(exc))
        return False
    if done.returncode != 0:
        logger.warning("pipeline_icloud_download_refused", path=path, returncode=done.returncode)
        return False
    logger.info("pipeline_icloud_download_requested", path=path)
    return True
