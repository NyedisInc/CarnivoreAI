
from __future__ import annotations

import asyncio
import collections
import json
import re
import secrets
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

import structlog

from src.core.computers import add_preview, store
from src.core.computers.add_preview import HostKeyJail
from src.core.computers.invites import MemberRefused, TooManyInvites
from src.core.computers.join_link import build_link
from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import SshDestination

log = structlog.get_logger(__name__)

JOB_DEADLINE_S = 1200.0
HELLO_DEADLINE_S = 60.0
LINK_POLL_S = 1.0
KEEP_FINISHED = 20
RING_BYTES = 4096

_LINE = re.compile(r"^(step|done|error) ([a-z0-9_]{1,40})(?: ([A-Za-z0-9_. -]{0,64}))?$")
_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_SCRIPT = (
    's="$(curl -fsSL --proto \'=https\' --tlsv1.2 https://carnivore.ai/install.sh)" && [ -n "$s" ] && '
    'exec /bin/bash -c "$s" _ --join --agent || { echo "error download_failed"; exit 1; }'
)
KNOWN_ERRORS = frozenset({
    "app_running", "app_running_too_old", "bad_link", "checksum_mismatch", "door_missing", "download_failed", "enrollment_failed",
    "install_failed", "join_timeout", "launch_failed", "local_network_blocked", "main_unreachable", "needs_homebrew", "needs_owner",
    "no_console_login", "server_timeout", "setup_timeout", "too_many_attempts", "unsupported_system", "usage", "verify_failed",
    "bad_code", "code_used_up", "code_expired", "no_pack_found", "bad_totp", "already_joined",
    "wrong_code", "expired", "no_invite", "busy", "rate_limited", "refused", "main_mismatch", "join_has_peers", "no_pack", "unreachable",
    "join_failed", "bad_request", "undetermined", "unavailable", "no_relay", "incompatible",
})
_STEPS = ("download", "install", "launch", "wait_server", "join_ready", "join", "connect")


class _Fail(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class AddJob:

    id: str
    target: str
    host_key_sha256: str
    state: str = "running"
    step: str = "checking_host_key"
    error: Optional[str] = None
    started_at: str = ""
    finished_at: Optional[str] = None
    computer: Optional[str] = None
    port: Optional[int] = None
    firewall_on: bool = False


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def installer_override(config_path: Path) -> Optional[Dict[str, str]]:
    try:
        doc = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    section = doc.get("computers") if isinstance(doc, dict) else None
    over = section.get("installer_override") if isinstance(section, dict) else None
    if (isinstance(over, dict) and all(isinstance(over.get(k), str) for k in ("script", "dmg", "sha256"))
            and _PATH.match(over["script"]) and _PATH.match(over["dmg"]) and _HEX64.match(over["sha256"])):
        return {k: over[k] for k in ("script", "dmg", "sha256")}
    return None


def remote_command(config_path: Path) -> str:
    over = installer_override(config_path)
    if over is not None:
        words = ["/bin/bash", over["script"], "--join", "--agent", "--dmg", over["dmg"], "--sha256", over["sha256"]]
        return "exec " + ssh_exec.posix_join(words)
    return _DEFAULT_SCRIPT


def _error_code(token: str) -> str:
    return token if token in KNOWN_ERRORS else "remote_error"


class _Ring:

    def __init__(self) -> None:
        self._buf: Deque[int] = collections.deque(maxlen=RING_BYTES)

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def text(self) -> str:
        return bytes(self._buf).decode("utf-8", "replace")


async def _drain(stream: Optional[asyncio.StreamReader], ring: _Ring) -> None:
    if stream is None:
        return
    while chunk := await stream.read(4096):
        ring.feed(chunk)


class AddJobs:

    def __init__(self) -> None:
        self._jobs: Dict[str, AddJob] = {}
        self._tasks: Set["asyncio.Task[None]"] = set()

    def clear(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._jobs.clear()

    def get(self, job_id: str) -> Optional[AddJob]:
        return self._jobs.get(job_id)

    def snapshot(self) -> List[Dict[str, Any]]:
        return [{k: v for k, v in asdict(j).items() if k != "port"} for j in self._jobs.values()]

    def firewall_on(self, install_id: str) -> bool:
        return any(j.firewall_on for j in self._jobs.values() if j.computer == install_id)

    def active_for(self, target: str, port: Optional[int]) -> Optional[AddJob]:
        return next((j for j in self._jobs.values() if j.target == target and j.port == port and j.state in ("running", "linking")), None)

    def start(self, rt: Any, dest: SshDestination, approved_fp: str) -> AddJob:
        job = AddJob(id=secrets.token_hex(4), target=dest.target, host_key_sha256=approved_fp, started_at=_now(), port=dest.port)
        self._jobs[job.id] = job
        finished = [j for j in self._jobs.values() if j.state in ("joined", "failed")]
        for old in finished[:-KEEP_FINISHED]:
            del self._jobs[old.id]
        task = asyncio.get_running_loop().create_task(_run(rt, job, dest))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        rt.notify("computers")
        return job


JOBS = AddJobs()


def _set(rt: Any, job: AddJob, **fields: Any) -> None:
    changed = {k: v for k, v in fields.items() if getattr(job, k) != v}
    for key, value in fields.items():
        setattr(job, key, value)
    if "step" in changed:
        log.info("computer_add_step", job=job.id, step=job.step)
    if changed:
        rt.notify("computers")


def _members(rt: Any) -> Dict[str, bool]:
    with closing(rt.open_db()) as conn:
        return {r.peer_install_id: r.first_link_at is not None for r in store.members_tls(conn)}


async def _send_link(rt: Any, job: AddJob, proc: asyncio.subprocess.Process) -> None:
    if rt.invites is None or rt.join_server is None or rt.identity is None:
        raise _Fail("computers_unavailable")
    try:
        inv = rt.invites.mint("ssh_add", job_id=job.id)
    except MemberRefused:
        raise _Fail("joined_computer") from None
    except TooManyInvites:
        raise _Fail("too_many_invites") from None
    try:
        await rt.join_server.sync()
    except OSError as exc:
        log.warning("computers_join_port_failed", error_type=type(exc).__name__)
    link = build_link(rt.addresses, rt.link_port, rt.identity.cert.der, inv)
    if link is None:
        raise _Fail("no_address")
    try:
        assert proc.stdin is not None
        proc.stdin.write((link + "\n").encode("ascii"))
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError, OSError):
        raise _Fail("ssh_failed") from None


async def _read_lines(rt: Any, job: AddJob, proc: asyncio.subprocess.Process) -> bool:
    assert proc.stdout is not None
    hello = joined = sent = False
    while True:
        try:
            raw = await (proc.stdout.readline() if hello else asyncio.wait_for(proc.stdout.readline(), HELLO_DEADLINE_S))
        except TimeoutError:
            raise _Fail("installer_too_old") from None
        except ValueError:
            raise _Fail("ssh_failed") from None
        if not raw:
            return joined
        match = _LINE.match(raw.decode("ascii", "replace").strip())
        if not hello:
            if match and match.group(1) == "error":
                raise _Fail(_error_code(match.group(2)))
            if not (match and match.group(1) == "step" and match.group(2) == "hello" and match.group(3) == "v1"):
                raise _Fail("installer_too_old")
            hello = True
            continue
        if match is None:
            continue
        kind, token = match.group(1), match.group(2)
        if kind == "error":
            raise _Fail(_error_code(token))
        if kind == "done":
            joined = joined or token == "joined"
        elif token == "firewall_on":
            _set(rt, job, firewall_on=True)
        elif token in _STEPS:
            _set(rt, job, step=token)
            if token == "join_ready" and not sent:
                sent = True
                await _send_link(rt, job, proc)


async def _await_final(rt: Any, job: AddJob, before: Set[str]) -> None:
    _set(rt, job, state="linking", step="linking")
    while True:
        rows = await asyncio.to_thread(_members, rt)
        final = next((iid for iid, done in rows.items() if iid not in before and done), None)
        if final is not None:
            _set(rt, job, state="joined", step="joined", computer=final, finished_at=_now())
            log.info("computer_add_joined", job=job.id, peer=final[:8])
            return
        await asyncio.sleep(LINK_POLL_S)


async def _execute(rt: Any, job: AddJob, dest: SshDestination, jail: HostKeyJail, held: Dict[str, Any]) -> None:
    before = set(await asyncio.to_thread(_members, rt))
    res, fp = await add_preview.first_contact(dest, jail)
    if fp is None:
        raise _Fail(add_preview.failure_code(res) or "unreachable")
    if fp != job.host_key_sha256:
        raise _Fail("host_key_changed")
    _set(rt, job, step="connecting")
    argv = ssh_exec.direct_argv(dest, remote_command(rt.config_path), ssh_binary=add_preview.SSH_BINARY, pre_options=jail.options("yes"))
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=8192)
    except OSError:
        raise _Fail("ssh_unavailable") from None
    ring = _Ring()
    held["proc"], held["drain"], held["ring"] = proc, asyncio.get_running_loop().create_task(_drain(proc.stderr, ring)), ring
    joined = await _read_lines(rt, job, proc)
    await asyncio.wait_for(proc.wait(), 15)
    if not joined:
        code = ssh_exec.classify_ssh_failure(ring.text()) if proc.returncode == 255 else "ssh_failed"
        log.info("computer_add_ssh_ended", job=job.id, rc=proc.returncode, failure=code)
        raise _Fail(code)
    await _await_final(rt, job, before)


async def _run(rt: Any, job: AddJob, dest: SshDestination) -> None:
    jail = HostKeyJail.create(job.id)
    held: Dict[str, Any] = {}
    code: Optional[str] = None
    try:
        async with asyncio.timeout(JOB_DEADLINE_S):
            await _execute(rt, job, dest, jail, held)
    except _Fail as exc:
        code = exc.code
    except TimeoutError:
        code = "timeout"
    except asyncio.CancelledError:
        code = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("computer_add_internal_error", job=job.id, error_type=type(exc).__name__)
        code = "internal_error"
    finally:
        proc = held.get("proc")
        if proc is not None:
            ssh_exec.signal_group(proc)
        drain = held.get("drain")
        if drain is not None:
            drain.cancel()
        jail.remove()
        if job.state != "joined":
            if rt.invites is not None:
                rt.invites.cancel_job(job.id)
            _set(rt, job, state="failed", error=code or "internal_error", finished_at=_now())
            log.info("computer_add_failed", job=job.id, code=job.error)
    if rt.join_server is not None:
        try:
            await rt.join_server.sync()
        except OSError as exc:
            log.warning("computers_join_port_failed", error_type=type(exc).__name__)
