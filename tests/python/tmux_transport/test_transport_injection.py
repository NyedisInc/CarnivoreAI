
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from src.core.hosts.remote_backend import make_remote_backend
from src.core.hosts.remote_transport import RemoteTransport
from src.core.tmux_transport.lifecycle import LocalLifecycle
from src.core.tmux_backend import TmuxBackend
from src.core.tmux_transport.local import LocalTransport
from src.core.tmux_transport.protocol import TmuxTransport


class RecordingTransport:

    host_key = "far"
    is_remote = True
    argv_visible_locally = False
    host = None

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Any]] = []

    def make_lifecycle(self, backend: Any) -> LocalLifecycle:
        return LocalLifecycle(backend)

    def argv_prefix(self, socket_name: str) -> List[str]:
        return ["fartmux", "-L", socket_name]

    def server_config_argv(self, commands: Sequence[Sequence[str]]) -> List[str]:
        self.calls.append(("config", [list(c) for c in commands]))
        return ["-f", "x"]

    async def run(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                  check: bool = True) -> Tuple[int, bytes, bytes]:
        self.calls.append(("run", (socket_name, tuple(args), stdin_bytes, check)))
        return 0, b"ran", b""

    def run_sync(self, socket_name: str, args: Sequence[str], *, stdin_bytes: Optional[bytes] = None,
                 check: bool = True, timeout: Optional[float] = None,
                 env: Optional[Dict[str, str]] = None, probe: bool = False) -> Tuple[int, bytes, bytes]:
        self.calls.append(("sync", (socket_name, tuple(args), timeout, probe)))
        return 0, b"sync", b""

    async def spawn_session(self, socket_name: str, args: Sequence[str], tmux_env: Dict[str, str],
                            config_commands: Sequence[Sequence[str]]) -> Tuple[int, bytes]:
        self.calls.append(("spawn", (socket_name, tuple(args))))
        return 0, b""


def test_both_transports_satisfy_the_protocol_with_the_same_methods() -> None:
    host = SimpleNamespace(host_key="studio", socket="far", tmux_path="/t")
    assert isinstance(LocalTransport(), TmuxTransport)
    assert isinstance(RemoteTransport(host), TmuxTransport)
    public = lambda cls: {n for n, v in vars(cls).items() if not n.startswith("_") and callable(v)}  # noqa: E731
    assert public(LocalTransport) <= public(RemoteTransport)


def test_the_default_transport_is_local_and_the_argument_is_keyword_only() -> None:
    backend = TmuxBackend("s1", Path("/tmp"))
    assert isinstance(backend._transport, LocalTransport) and backend.host_key == "local"
    assert inspect.signature(TmuxBackend.__init__).parameters["transport"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_an_injected_transport_carries_every_command_and_the_identity() -> None:
    transport = RecordingTransport()
    backend = TmuxBackend("s1", Path("/tmp"), socket_name="sock", transport=transport)
    assert (backend.is_remote, backend.host_key) == (True, "far")
    assert backend._tmux_base() == ["fartmux", "-L", "sock"]
    assert await backend._run_tmux("has-session", "-t", "=x", check=False) == (0, b"ran", b"")
    assert backend._run_tmux_sync("list-sessions", timeout=3.0, probe=True) == (0, b"sync", b"")
    assert await backend._spawn_session(["new-session"], {}) == (0, b"")
    assert backend._server_config_argv() == ["-f", "x"]
    assert ("run", ("sock", ("has-session", "-t", "=x"), None, False)) in transport.calls
    assert ("sync", ("sock", ("list-sessions",), 3.0, True)) in transport.calls


@pytest.mark.asyncio
async def test_secrets_use_stdin_only_where_argv_is_visible_locally() -> None:
    transport = RecordingTransport()
    backend = TmuxBackend("s1", Path("/tmp"), socket_name="sock", transport=transport)
    await backend._run_tmux_private("set-environment", "-t", "=x", "K", "v", check=False)
    assert transport.calls == [("run", ("sock", ("set-environment", "-t", "=x", "K", "v"), None, False))]


def test_there_is_no_remote_backend_subclass() -> None:
    from src.core.hosts import remote_backend

    assert not hasattr(remote_backend, "RemoteTmuxBackend")
    host = SimpleNamespace(host_key="studio", socket="far", tmux_path="/t")
    assert type(make_remote_backend(host, "s1", Path("/far"))) is TmuxBackend


def test_the_remote_backend_is_built_on_a_remote_transport() -> None:
    host = SimpleNamespace(host_key="studio", socket="far", tmux_path="/t")
    backend = make_remote_backend(host, "s1", Path("/far"))
    assert isinstance(backend._transport, RemoteTransport) and backend.host_key == "studio"
