
from __future__ import annotations

from typing import Any, Optional, Tuple

from fastapi import HTTPException

from src.core.hosts.identity import is_remote_backend, parse_remote_session_id
from src.api.error_response import api_error

REMOTE_HOST_CODE = "remote_host"


def remote_target(manager: Any, value: Optional[str]) -> Optional[Tuple[str, str]]:
    parsed = parse_remote_session_id(value)
    if parsed is not None:
        return parsed
    registry = getattr(manager, "_registry", None)
    backend = getattr(registry, "backends", {}).get(value) if value else None
    if is_remote_backend(backend):
        return backend.host_key, str(backend.tmux_session)
    return None


def routed_remote(manager: Any, value: Optional[str]) -> Optional[Any]:
    from src.core.hosts.remote_controls import resolve_remote

    try:
        return resolve_remote(manager, value)
    except LookupError as exc:
        raise api_error(404, "not_found", exc, step="routed_remote") from exc


def remote_refusal(host_key: str, action: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": REMOTE_HOST_CODE,
        "detail": f"this session runs on host {host_key}; {action} acts on this machine "
                  "and is not available for a remote session"})


def refuse_remote(manager: Any, value: Optional[str], action: str) -> None:
    found = remote_target(manager, value)
    if found is not None:
        raise remote_refusal(found[0], action)
