
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.core.tmux_listing import TmuxListing


@runtime_checkable
class Clock(Protocol):

    def now(self) -> float:
        ...

    def monotonic(self) -> float:
        ...


@runtime_checkable
class SettingsReader(Protocol):

    def pinned_themes_path(self) -> Path:
        ...

    def log_buffer_size(self) -> int:
        ...

    def state_dir(self) -> Path:
        ...

    def session_metadata_path(self) -> Path:
        ...


@runtime_checkable
class TmuxReader(Protocol):

    def is_alive(self) -> bool:
        ...

    def discover_existing(self) -> "TmuxListing":
        ...

    def list_pane_status_all(self, *, fresh: bool = False) -> "TmuxListing":
        ...

    def capture_scrollback(self, lines: int = 3000) -> bytes:
        ...

    def capture_visible_screen(self) -> bytes:
        ...


@runtime_checkable
class ReadConnection(Protocol):

    def execute(self, sql: str, parameters: Any = ..., /) -> sqlite3.Cursor:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class SessionRecordStore(Protocol):

    def read_connection(self) -> Optional[ReadConnection]:
        ...

    def write_connection(self) -> Optional[sqlite3.Connection]:
        ...

    def get_instance(
        self, *, socket: str, name: str, epoch: Optional[int]
    ) -> Optional[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class Target:

    harness: str
    leaf_dir: Path


@runtime_checkable
class InstallRoots(Protocol):

    def targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        ...

    def required_manifest(self, kind: str) -> str:
        ...

    def trash_dir(
        self, harness: str, scope: str, project_path: str | None
    ) -> Path:
        ...

    def staging_dir(self) -> Path:
        ...

    def pending_dir(self) -> Path:
        ...

    def root_listing(self, harness: str) -> tuple[str, ...]:
        ...

    def read_only_listing(self, harness: str) -> tuple[str, ...]:
        ...

    def present_harnesses(self) -> tuple[str, ...]:
        ...

    def legacy_targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        ...


@runtime_checkable
class SessionManagerSurface(Protocol):

    _registry: Any
    _borrowed: Any
    _instance_epochs: dict[str, int]
    _unread_store: Any
    _wrappers_reader: Any
    _attention_watcher: Any

    def _name_read_connection(self) -> Any: ...

    def _writable_datastore_connection(self) -> Any: ...

    def _make_output_handler(self, session_id: str) -> Any: ...

    def _make_viewer_probe(self, session_id: str) -> Any: ...

    async def _cleanup_failed_create(self, session_id: str, backend: Any) -> None: ...
