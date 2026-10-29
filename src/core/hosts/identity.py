
from __future__ import annotations

from typing import Any, Optional, Tuple

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.store import KEY_RE

REMOTE_ID_PREFIX = "remote:"

REMOTE_ROOT_SCHEME = "ssh://"

PEER_ROOT_SCHEME = "peer://"


def remote_session_id(host_key: str, tmux_name: str) -> str:
    if host_key == LOCAL_HOST_KEY or KEY_RE.fullmatch(host_key or "") is None:
        raise ValueError(f"not a remote host key: {host_key!r}")
    if not tmux_name or ":" in tmux_name:
        raise ValueError(f"not a tmux session name: {tmux_name!r}")
    return f"{REMOTE_ID_PREFIX}{host_key}:{tmux_name}"


def parse_remote_session_id(value: Optional[str]) -> Optional[Tuple[str, str]]:
    if not value or not value.startswith(REMOTE_ID_PREFIX):
        return None
    host_key, sep, name = value[len(REMOTE_ID_PREFIX):].partition(":")
    if (not sep or host_key == LOCAL_HOST_KEY or KEY_RE.fullmatch(host_key) is None
            or not name or ":" in name):
        return None
    return host_key, name


def remote_project_root(host_key: str, far_path: str) -> str:
    return f"{REMOTE_ROOT_SCHEME}{host_key}{far_path}"


def is_remote_root(root: Optional[str]) -> bool:
    return bool(root) and str(root).startswith((REMOTE_ROOT_SCHEME, PEER_ROOT_SCHEME))


def is_remote_backend(backend: Any) -> bool:
    from src.core.hosts.remote_backend import RemoteTmuxBackend

    return isinstance(backend, RemoteTmuxBackend)


def backend_host_key(backend: Any) -> str:
    return backend.host_key if is_remote_backend(backend) else LOCAL_HOST_KEY


def instance_name(backend: Any) -> Optional[str]:
    name = getattr(backend, "tmux_session", None) if backend is not None else None
    if not name:
        return None
    if is_remote_backend(backend):
        return f"{REMOTE_ID_PREFIX}{backend.host_key}:{name}"
    return str(name)


def is_remote_info(info: Any) -> bool:
    return (getattr(info, "host_key", None) or LOCAL_HOST_KEY) != LOCAL_HOST_KEY
