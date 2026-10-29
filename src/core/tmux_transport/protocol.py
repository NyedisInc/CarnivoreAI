
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from src.core.tmux_listing import TmuxListing

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend
    from src.core.tmux_transport.lifecycle import PaneLifecycle


@runtime_checkable
class TmuxTransport(Protocol):

    host_key: str
    is_remote: bool
    argv_visible_locally: bool
    host: Optional[Any]

    def argv_prefix(self, socket_name: str) -> List[str]:
        ...

    def server_config_argv(self, commands: Sequence[Sequence[str]]) -> List[str]:
        ...

    async def run(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                  check: bool = True) -> Tuple[int, bytes, bytes]:
        ...

    def run_sync(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                 check: bool = True, timeout: Optional[float] = None,
                 env: Optional[Dict[str, str]] = None, probe: bool = False) -> Tuple[int, bytes, bytes]:
        ...

    async def spawn_session(self, socket_name: str, args: Sequence[str], tmux_env: Dict[str, str],
                            config_commands: Sequence[Sequence[str]]) -> Tuple[int, bytes]:
        ...


    def pipe_read_path(self, tmux_slug: str, backend_slug: str) -> Path:
        ...

    def pipe_write_path(self, read_path: Path, backend_slug: str) -> str:
        ...

    async def ensure_pipe_file(self, read_path: Path, write_path: str, *, truncate: bool) -> None:
        ...

    async def pipe_file_exists(self, write_path: str) -> bool:
        ...

    def preflight(self, socket_name: str, working_dir: Path) -> None:
        ...


    listing_errors: Tuple[type, ...]

    def listing_gate(self) -> Optional[TmuxListing]:
        ...

    def listing_failure(self, exc: BaseException, socket_name: str, args: Sequence[str]) -> TmuxListing:
        ...

    def pane_listing_cache_key(self, socket_name: str) -> Optional[str]:
        ...

    def shape_pane_listing(self, listing: TmuxListing) -> TmuxListing:
        ...

    def make_lifecycle(self, backend: "TmuxBackend") -> "PaneLifecycle":
        ...
