
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.core.hosts.remote_host import RemoteHost
from src.core.hosts.remote_transport import RemoteTransport
from src.core.tmux_backend import TmuxBackend


def make_remote_backend(host: RemoteHost, session_id: str, working_dir: Path,
                        on_output: Optional[Callable[[bytes], Any]] = None, *,
                        scrollback_lines: int = 3000, session_name: Optional[str] = None,
                        viewer_probe: Optional[Callable[[], bool]] = None,
                        stream_options: Optional[Dict[str, Any]] = None) -> TmuxBackend:
    return TmuxBackend(session_id, working_dir, on_output, socket_name=host.socket,
                       scrollback_lines=scrollback_lines, session_name=session_name,
                       viewer_probe=viewer_probe, transport=RemoteTransport(host, stream_options))
