
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.computers import commit, join_client
from src.core.computers.join_client import JoinFailed
from src.core.computers.join_link import parse_link
from src.core.computers.membership import first_run_state, set_join_running
from src.core.computers.tls_identity import LinkIdentity
from src.core.federation.discovery import sanitize_pack_name
from src.core.relay_identity.device_key import DeviceKey

RELAY_WAIT_SECONDS = 120.0
RELAY_FAIL_CODES = ("no_pack", "unreachable", "local_network_blocked", "several")
LOOK_FAIL_CODES = ("no_pack", "local_network_blocked", "found")

log = structlog.get_logger(__name__)


class JoinNotAllowed(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class JoinDeps:

    identity: LinkIdentity
    fed_key: DeviceKey
    public_key: str
    own_iid: str
    own_label: str
    open_db: commit.OpenDb
    links: commit.Links
    pack: commit.PackSettingsPort
    reserve_port: Callable[[], Awaitable[Optional[int]]]
    release_port: Callable[[], Awaitable[None]]
    addresses: Callable[[], List[str]]
    app_version: str = ""
    notify: Optional[commit.Notify] = None
    join: Callable[..., Awaitable[join_client.JoinOutcome]] = join_client.join


@dataclass
class JoinJob:

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "idle"
    error: Optional[str] = None
    main_label: Optional[str] = None
    main_iid: Optional[str] = None
    tries_left: Optional[int] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    running: bool = False

    def status(self) -> Dict[str, Any]:
        return {"state": self.state, "error": self.error, "main_label": self.main_label, "main_iid": self.main_iid,
                "tries_left": self.tries_left, "candidates": list(self.candidates)}


_deps: Optional[JoinDeps] = None
_job: Optional[JoinJob] = None
_task: Optional["asyncio.Task[None]"] = None
_pending: Optional["_Pending"] = None


@dataclass
class _Pending:

    code: Optional[str]
    parsed: Any
    candidate_fid: Optional[str]
    require_grant: bool
    look: bool = False


def configure_join(deps: Optional[JoinDeps]) -> None:
    global _deps
    _deps = deps


def current_job() -> Optional[JoinJob]:
    return _job


def join_status() -> Dict[str, Any]:
    if first_run_state() == "joined":
        if _job is not None and _job.state == "joined":
            return _job.status()
        return JoinJob(state="joined").status()
    return (_job or JoinJob()).status()


def window_status() -> Dict[str, Any]:
    status = join_status()
    if status["state"] == "joined" and first_run_state() != "joined":
        status["state"] = "linking"
    return status


def start_join(code: Optional[str], link: Optional[str], candidate_fid: Optional[str] = None, *, origin: str,
               totp_ok: bool) -> JoinJob:
    global _job, _task, _pending
    if _job is not None and _job.running:
        if _pending is None or not _pending.look:
            return _job
    state = first_run_state()
    if state == "join_pending" and _job is not None and _job.state == "joined":
        return _job
    if state == "joined":
        raise JoinNotAllowed("already_joined")
    if state == "undetermined":
        raise JoinNotAllowed("undetermined")
    if (code is None) == (link is None) or (code is not None and not (len(code) == 6 and code.isascii() and code.isdigit())):
        raise JoinNotAllowed("bad_request")
    parsed = parse_link(link) if link is not None else None
    if link is not None and parsed is None:
        raise JoinNotAllowed("bad_link")
    if _deps is None:
        raise JoinNotAllowed("unavailable")
    if _job is not None and _job.running:
        _end_look(_job)
    job = JoinJob(state="waiting_relay", running=True)
    _job = job
    _pending = _Pending(code, parsed, candidate_fid, require_grant=state == "paired" and not totp_ok)
    set_join_running(True)
    log.info("computer_join_start", origin=origin, mode="link" if parsed else "code", needs_grant=_pending.require_grant)
    _task = asyncio.get_running_loop().create_task(_expire(job))
    return job


def _end_look(job: JoinJob) -> None:
    global _pending
    if _task is not None and not _task.done():
        _task.cancel()
    _pending = None
    job.state, job.error, job.running = "failed", "superseded", False


def start_look(*, origin: str) -> JoinJob:
    global _job, _task, _pending
    if _job is not None and _job.running:
        return _job
    state = first_run_state()
    if state == "join_pending" and _job is not None and _job.state == "joined":
        return _job
    if state == "joined":
        raise JoinNotAllowed("already_joined")
    if state == "undetermined":
        raise JoinNotAllowed("undetermined")
    if _deps is None:
        raise JoinNotAllowed("unavailable")
    job = JoinJob(state="waiting_relay", running=True)
    _job = job
    _pending = _Pending(None, None, None, require_grant=False, look=True)
    log.info("computer_look_start", origin=origin)
    _task = asyncio.get_running_loop().create_task(_expire(job))
    return job


def relay_request() -> Optional[Dict[str, Any]]:
    if _job is None or _pending is None or _job.state != "waiting_relay":
        return None
    parsed = _pending.parsed
    mode = "look" if _pending.look else "link" if parsed is not None else "code"
    return {"job": _job.id, "mode": mode, "candidate_fid": _pending.candidate_fid,
            "targets": [[h, parsed.link_port + 1] for h in parsed.hosts] if parsed is not None else []}


def _finish(job: JoinJob, state: str, error: Optional[str] = None) -> None:
    global _pending
    _pending = None
    job.state, job.error, job.running = state, error, False
    set_join_running(False)


async def _expire(job: JoinJob) -> None:
    await asyncio.sleep(RELAY_WAIT_SECONDS)
    if _job is job and job.state == "waiting_relay":
        _finish(job, "failed", "no_relay")
        log.info("computer_join_failed", code="no_relay")


async def attach_relay(path: str, address: str, expect_fid: Optional[str], job_id: Optional[str] = None) -> JoinJob:
    global _pending, _task
    job, pend, deps = _job, _pending, _deps
    if job is None or pend is None or deps is None or job.state != "waiting_relay" or (job_id is not None and job_id != job.id):
        raise JoinNotAllowed("no_join_waiting")
    if pend.look:
        raise JoinNotAllowed("no_join_waiting")
    if pend.candidate_fid and expect_fid and pend.candidate_fid != expect_fid:
        _finish(job, "failed", "main_mismatch")
        return job
    if _task is not None and not _task.done():
        _task.cancel()
    job.state, _pending = "connecting", None
    log.info("computer_join_relay_attached", addr=address[:64])
    _task = asyncio.get_running_loop().create_task(_run_job(job, deps, path, pend, pend.candidate_fid or expect_fid))
    return job


def _candidate(raw: Dict[str, Any]) -> Dict[str, Any]:
    fid = str(raw.get("fid") or "")[:64]
    name, short = (sanitize_pack_name(raw.get(k)) or "" for k in ("name", "fid_short"))
    pack_name = sanitize_pack_name(raw.get("pack_name"))
    return {"name": name, "fid": fid, "fid_short": short, "pack_name": pack_name,
            "label": f"{pack_name} {short}".strip() if pack_name else f"{name} {short}".strip()}


def fail_relay(code: str, candidates: Optional[List[Dict[str, Any]]] = None, job_id: Optional[str] = None) -> JoinJob:
    """The helper could not reach main: ``code`` is one of ``RELAY_FAIL_CODES`` (a look: ``LOOK_FAIL_CODES``). ``several`` (a look: ``found``)
    ends the job in ``finding`` with ``candidates`` (``{name, fid, fid_short, pack_name}`` in, ``+ label`` out) for the window's pick step. ``job_id``, when given, must be the waiting job's. Raises JoinNotAllowed("no_join_waiting") or ("bad_request").

    Example: ``fail_relay("no_pack")``.
    """
    job = _job
    if job is None or _pending is None or job.state != "waiting_relay" or (job_id is not None and job_id != job.id):
        raise JoinNotAllowed("no_join_waiting")
    if code not in (LOOK_FAIL_CODES if _pending.look else RELAY_FAIL_CODES):
        raise JoinNotAllowed("bad_request")
    if code in ("several", "found"):
        job.candidates = [_candidate(c) for c in (candidates or [])[:16] if isinstance(c, dict)]
        _finish(job, "finding" if job.candidates else "failed", None if job.candidates else "no_pack")
    else:
        _finish(job, "failed", code)
    log.info("computer_join_relay_failed", code=code)
    return job


def end_waiting(job: JoinJob, code: str) -> None:
    """End ``job`` ``failed`` with ``code`` when it still waits for a helper (the server could not start one). Example: ``end_waiting(job, "helper_not_started")``."""
    if _job is job and job.state == "waiting_relay":
        _finish(job, "failed", code)
        log.info("computer_join_failed", code=code)


def end_waiting_by_id(job_id: str, code: str) -> None:
    if _job is not None and _job.id == job_id:
        end_waiting(_job, code)


async def _run_job(job: JoinJob, deps: JoinDeps, relay_path: str, pend: _Pending, expect_fid: Optional[str]) -> None:
    try:
        port = await deps.reserve_port()
        if port is None:
            raise JoinFailed("join_failed")
        parsed = pend.parsed
        extra: Dict[str, Any] = ({"mode": "invite", "secret": parsed.secret, "invite_id": parsed.invite_id, "expect_cert_k": parsed.k}
                                 if parsed else {"mode": "code", "code": pend.code})
        out = await deps.join(relay_path=relay_path, listen_port=port, listen_addresses=list(deps.addresses()), identity=deps.identity,
                              fed_key=deps.fed_key, public_key=deps.public_key, own_iid=deps.own_iid, own_label=deps.own_label,
                              open_db=deps.open_db, links=deps.links, pack=deps.pack, expect_fid=expect_fid,
                              require_existing_grant=pend.require_grant, app_version=deps.app_version, notify=deps.notify, **extra)
        job.state, job.main_label, job.main_iid = "joined", out.main_label, out.main_install_id
        log.info("computer_join_provisional", kind=out.kind)
    except JoinFailed as exc:
        job.state, job.error, job.tries_left = "failed", exc.code, exc.left
        log.info("computer_join_failed", code=exc.code)
    except commit.JoinRefused as exc:
        job.state, job.error = "failed", "refused"
        log.info("computer_join_failed", code="refused", reason=str(exc)[:80])
    except Exception as exc:  # noqa: BLE001
        job.state, job.error = "failed", "join_failed"
        log.error("computer_join_crashed", error_type=type(exc).__name__)
    finally:
        job.running = False
        set_join_running(False)
        await deps.release_port()


def candidate_view() -> List[Dict[str, Any]]:
    return [] if _job is None else list(_job.candidates)
