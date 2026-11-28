
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Protocol, Sequence, Tuple

import structlog

logger = structlog.get_logger()

BOOT_GRACE_SECONDS: float = 300.0


class FallbackUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FallbackConversation:

    conversation_id: str
    family: str
    signature: str
    working_dir: Optional[str] = None
    sha256: Optional[str] = None
    title: Optional[str] = None
    session_uuid: Optional[str] = None
    project_name: Optional[str] = None
    hidden: bool = False


@dataclass(frozen=True)
class FallbackFile:

    conversation_id: str
    family: str
    file_kind: str
    source_path: str
    rel: str
    length: int
    signature: str
    working_dir: Optional[str] = None


@dataclass(frozen=True)
class FallbackEntry:

    conversation_id: str
    family: str
    role: str
    home: str
    rel: str
    source_path: str
    length: int
    signature: str
    mode: int = 0
    mtime_ns: int = 0


@dataclass(frozen=True)
class FallbackPointFile:

    role: str
    home: str
    rel: str
    source_path: str
    length: int
    sha256: str
    mode: int = 0
    mtime_ns: int = 0
    lines: int = 0


@dataclass(frozen=True)
class IncomingFile(FallbackPointFile):

    read: Optional[Callable[[], Iterator[bytes]]] = None


@dataclass(frozen=True)
class FallbackPoint:

    conversation_id: str
    point_id: str
    reason: str
    created_epoch: float
    created_at: str
    family: str
    files: Tuple[FallbackPointFile, ...]
    session_uuid: Optional[str] = None
    project_uid: Optional[str] = None
    project_name: Optional[str] = None
    working_dir: Optional[str] = None
    encoded_folder: Optional[str] = None
    wrapper: Optional[str] = None
    title: Optional[str] = None
    kind: str = "conversation"
    tags: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class AdoptedPoint:

    conversation_id: str
    source_point_id: str
    status: str
    point_id: str = ""
    reason: str = ""
    manifest_sha256: str = ""
    new_chunks: Tuple[str, ...] = ()


class FallbackReader(Protocol):

    length: int

    def read(self, offset: int, length: int) -> bytes:
        pass

    def lines(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:
        pass


class FallbackSource(Protocol):

    def conversations(self) -> Iterable[FallbackConversation]:
        pass

    def files(self, conversation_id: str) -> List[FallbackFile]:
        pass

    def reader(self, conversation_id: str, source_path: str, file_kind: str) -> FallbackReader:
        pass

    def entries(self, conversation_id: str) -> List[FallbackEntry]:
        pass

    def entry_reader(self, conversation_id: str, rel: str) -> FallbackReader:
        pass

    def list_points(self, conversation_id: str) -> List[FallbackPoint]:
        pass

    def list_folder_points(self, unit: str) -> List[FallbackPoint]:
        pass

    def point_entry_reader(self, conversation_id: str, point_id: str, rel: str) -> FallbackReader:
        pass

    def adopt_points(self, points: Sequence[FallbackPoint], log: Callable[[Dict[str, Any]], None]) -> List[AdoptedPoint]:
        pass

    def remove_adopted(self, entries: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
        pass


def path_tail(path: str, conversation_id: str) -> str:
    parts = [p for p in path.split("/") if p]
    folders = parts[:-1]
    if conversation_id in folders:
        return "/".join(parts[len(folders) - folders[::-1].index(conversation_id):])
    return parts[-1] if parts else ""


_lock = threading.Lock()
_sources: Dict[str, FallbackSource] = {}


def register(source_id: str, source: FallbackSource) -> None:
    with _lock:
        _sources[source_id] = source


def unregister(source_id: str) -> None:
    with _lock:
        _sources.pop(source_id, None)


def registered(source_id: str) -> bool:
    with _lock:
        return source_id in _sources


def sources() -> Tuple[FallbackSource, ...]:
    with _lock:
        return tuple(_sources.values())


_gone_listeners: List[Callable[[str], None]] = []


def on_conversation_gone(listener: Callable[[str], None]) -> None:
    with _lock:
        if listener not in _gone_listeners:
            _gone_listeners.append(listener)


def remove_gone_listener(listener: Callable[[str], None]) -> None:
    with _lock:
        if listener in _gone_listeners:
            _gone_listeners.remove(listener)


def notify_conversation_gone(conversation_id: str) -> int:
    with _lock:
        listeners = tuple(_gone_listeners)
    if not listeners:
        logger.debug("fallback_gone_nobody_listening", conversation_id=conversation_id)
    for listener in listeners:
        try:
            listener(conversation_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fallback_gone_listener_failed", conversation_id=conversation_id, error_type=type(exc).__name__, error=str(exc)[:200])
    return len(listeners)


_boot_deadline: float = float("-inf")


def begin_boot(grace: float = BOOT_GRACE_SECONDS) -> None:
    global _boot_deadline
    with _lock:
        _boot_deadline = time.monotonic() + float(grace)


def end_boot() -> None:
    global _boot_deadline
    with _lock:
        _boot_deadline = float("-inf")


def booting() -> bool:
    with _lock:
        return time.monotonic() < _boot_deadline


__all__ = ["path_tail", "BOOT_GRACE_SECONDS", "FallbackConversation", "FallbackFile", "FallbackReader", "FallbackSource", "FallbackUnavailable",
           "begin_boot", "booting", "end_boot", "notify_conversation_gone", "on_conversation_gone", "register", "remove_gone_listener", "sources", "unregister"]
