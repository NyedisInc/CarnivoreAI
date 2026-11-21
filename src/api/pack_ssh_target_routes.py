
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth, security
from src.api.error_response import api_error
from src.api.hosts_routes import _call
from src.core.api_keys.store import is_api_key
from src.core.hosts import store as hosts_store
from src.core.pack.jobs.ssh import owner
from src.core.pack.jobs.types import JobError

logger = structlog.get_logger()


async def _owner_only(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "ssh_target_owner_only")


router = APIRouter(prefix="/pack/ssh-targets", tags=["pack-ssh-targets"], dependencies=[Depends(require_auth), Depends(_owner_only)])


class TargetBody(BaseModel):
    """The owner's settings of one ssh computer. Example: {"takes_work": true, "host_key_sha256": "SHA256:..."}."""

    model_config = ConfigDict(extra="forbid")
    takes_work: bool
    host_key_sha256: Optional[str] = Field(default=None, pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    labels: Optional[List[str]] = Field(default=None, max_length=16)
    reserve: Optional[Dict[str, Any]] = None


def _job_error(exc: JobError) -> Exception:
    return api_error(exc.status, exc.code, exc)


def _not_target(exc: "owner.NotJobTarget") -> Exception:
    return api_error(409, "not_a_job_target", exc, extra={"reason": exc.reason, "message": exc.detail})


async def _host(host_key: str) -> Any:
    host, _counts = await _call(hosts_store.get_host, host_key)
    return host


def _store() -> Any:
    try:
        return owner.job_store()
    except JobError as exc:
        raise _job_error(exc) from exc


@router.get("")
async def list_targets() -> Dict[str, Any]:
    """Every ssh computer (not this one, not a paired one) with its state. Output: {targets: [...]}; each has the keys of ``owner.view_of``."""
    store = _store()
    hosts, _counts = await _call(hosts_store.list_hosts)
    return {"targets": await owner.all_views(store, hosts)}


@router.put("/{host_key}")
async def put_target(host_key: str, body: TargetBody) -> Dict[str, Any]:
    """Turn takes-work on or off and set labels and reserve; output: {target}.

    Turning it on needs the host key the owner confirmed: without ``host_key_sha256`` (or with one that is not the key the computer shows now) the
    answer is 409 ``confirm_host_key`` with ``fingerprints`` to show, and nothing is pinned. An existing pin is replaced only by a PUT that carries
    the new fingerprint. Raises 404 host_not_found, 409 not_a_job_target or confirm_host_key, 422 bad_settings, 502 unreachable.
    """
    store = _store()
    host = await _host(host_key)
    try:
        await owner.apply_settings(store, host, takes_work=body.takes_work, fingerprint=body.host_key_sha256, labels=body.labels, reserve=body.reserve)
    except owner.ConfirmHostKey as exc:
        raise api_error(409, "confirm_host_key", extra=exc.shown) from exc
    except owner.NotJobTarget as exc:
        raise _not_target(exc) from exc
    except ValueError as exc:
        raise api_error(422, "bad_settings", exc) from exc
    except JobError as exc:
        raise _job_error(exc) from exc
    return {"target": await owner.target_view(store, host)}


@router.post("/{host_key}/probe")
async def probe_target(host_key: str) -> Dict[str, Any]:
    """Hello and the probe of one confirmed computer, one per 60 seconds; output: {fresh, hello, target}.

    ``fresh`` is false (and ``hello`` null) when the last probe was under a minute ago. Raises 404, 409 not_a_job_target or host_key_unverified.
    """
    store = _store()
    host = await _host(host_key)
    try:
        fresh, hello = await owner.probe(store, host)
    except owner.NotJobTarget as exc:
        raise _not_target(exc) from exc
    except JobError as exc:
        raise _job_error(exc) from exc
    return {"fresh": fresh, "hello": hello, "target": await owner.target_view(store, host)}


@router.delete("/{host_key}/folders")
async def delete_folders(host_key: str) -> Dict[str, Any]:
    """Remove every project's far cache and folders on one computer and sweep it; output: {forgotten, kept, refused}.

    Refused with 409 ``jobs_running`` while a job there is live. A slot the owner kept with keep_files stays and is named in ``kept``.
    """
    store = _store()
    host = await _host(host_key)
    if owner.refusal(host) is not None:
        raise _not_target(owner.NotJobTarget(*owner.refusal(host)))
    try:
        return await owner.forget_folders(store, host)
    except JobError as exc:
        raise _job_error(exc) from exc
