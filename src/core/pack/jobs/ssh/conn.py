
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

import structlog

from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import ExecResult, SshDestination
from src.core.hosts.ssh_master import SshTransportError
from src.core.hosts.ssh_pool import SshMasterPool, ShellNotVerified
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

KNOWN_HOSTS_NAME = "ssh-jobs-known_hosts"
FINGERPRINT_RE = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")
_KEY_LINE_RE = re.compile(r"(ssh-[a-z0-9-]+|ecdsa-sha2-nistp[0-9]+|sk-[a-z0-9@.-]+) ([A-Za-z0-9+/]+={0,2})")
_FAR_ROOT_RE = re.compile(r"/[A-Za-z0-9._+/-]{1,255}")
_BLOB_ID_RE = re.compile(r"[0-9a-f]{16,128}")
_JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")

MAX_CALLS_IN_FLIGHT = 4
STDERR_CAP = 4096
MAX_DOWNLOAD = 2 << 30
_CHUNK = 1 << 16

UPLOAD_FAR_SCRIPT = 'umask 077; mkdir -p "$1/in" && exec cat > "$1/in/$2.part"'
DOWNLOAD_FAR_SCRIPT = 'exec cat -- "$1/out/$2.bundle"'

_SAFE_PATH_RE = re.compile(r"/[A-Za-z0-9._+/-]+")
_JOBS_LINE_RE = re.compile(r"cvjob-[0-9a-f]{16} \S+ \S+")
TRANSFER_BASE_SECONDS = 60.0
TRANSFER_FLOOR_RATE = 256 * 1024
IDLE_READ_S = 60.0
UNREACHABLE = "the computer could not be reached over ssh"

_pin_lock = threading.Lock()



def known_hosts_path(state_dir: Path) -> Path:
    path = Path(state_dir) / "pack" / KNOWN_HOSTS_NAME
    if _SAFE_PATH_RE.fullmatch(str(path)) is not None:
        return path
    return Path.home() / ".carnivore" / "ssh-jobs" / instance_tag(state_dir) / KNOWN_HOSTS_NAME


def host_alias(host_key: str) -> str:
    return "cvjob-" + hashlib.sha256(host_key.encode("utf-8")).hexdigest()[:16]


def instance_tag(state_dir: Path) -> str:
    return hashlib.sha256(f"{state_dir}:jobs".encode("utf-8")).hexdigest()[:8]


def jobs_pre_options(host_key: str, known_hosts: Path) -> List[Tuple[str, str]]:
    if _SAFE_PATH_RE.fullmatch(str(known_hosts)) is None:
        raise JobError("bad_known_hosts_path", "the jobs known_hosts path holds a character ssh would split or expand", 500)
    return [
        ("UserKnownHostsFile", str(known_hosts)), ("GlobalKnownHostsFile", "/dev/null"),
        ("StrictHostKeyChecking", "yes"), ("HostKeyAlias", host_alias(host_key)),
        ("UpdateHostKeys", "no"), ("VerifyHostKeyDNS", "no"), ("KnownHostsCommand", "none"),
        ("CheckHostIP", "no"), ("PermitLocalCommand", "no"), ("RequestTTY", "no"),
    ]


def fingerprint_of(public_key: str) -> str:
    match = _KEY_LINE_RE.fullmatch((public_key or "").strip())
    if match is None:
        raise JobError("bad_host_key", "the host key is not a public key line", 400)
    try:
        blob = base64.b64decode(match.group(2), validate=True)
    except binascii.Error as exc:
        raise JobError("bad_host_key", "the host key is not valid base64", 400) from exc
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def _pinned_lines(path: Path, alias: str) -> List[str]:
    try:
        text = path.read_text(encoding="ascii", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        name, _, rest = line.partition(" ")
        if name == alias and _KEY_LINE_RE.fullmatch(rest.strip()):
            out.append(rest.strip())
    return out


def pin_key(host_key: str, sha256: str, public_key: str, state_dir: Path) -> Path:
    if FINGERPRINT_RE.fullmatch(sha256 or "") is None:
        raise JobError("bad_fingerprint", "a host key fingerprint is SHA256: plus 43 base64 characters", 400)
    if fingerprint_of(public_key) != sha256:
        raise JobError("fingerprint_mismatch", "the host key does not match the confirmed fingerprint", 409)
    alias, path = host_alias(host_key), known_hosts_path(state_dir)
    with _pin_lock:
        if _pinned_lines(path, alias):
            raise JobError("already_pinned", "this computer already has a pinned host key", 409)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        try:
            existing = path.read_text(encoding="ascii", errors="replace")
        except FileNotFoundError:
            existing = ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(f"{existing}{alias} {public_key.strip()}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
            raise
    log.info("ssh_jobs_key_pinned", host=host_key, fingerprint=sha256)
    return path


def unpin_key(host_key: str, state_dir: Path) -> bool:
    alias, path = host_alias(host_key), known_hosts_path(state_dir)
    with _pin_lock:
        try:
            lines = path.read_text(encoding="ascii", errors="replace").splitlines()
        except FileNotFoundError:
            return False
        kept = [x for x in lines if x.partition(" ")[0] != alias]
        if len(kept) == len(lines):
            return False
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write("".join(f"{x}\n" for x in kept))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
            raise
    log.info("ssh_jobs_key_unpinned", host=host_key)
    return True



@contextlib.contextmanager
def _transport_errors() -> Iterator[None]:
    try:
        yield
    except ShellNotVerified as exc:
        log.info("ssh_jobs_shell_not_verified", error=type(exc).__name__)
        raise JobError("shell_not_posix", "the login shell of that computer is not a POSIX shell this computer can use", 503) from exc
    except SshTransportError as exc:
        log.info("ssh_jobs_transport_error", error=type(exc).__name__)
        raise JobError("unreachable", UNREACHABLE, 503) from exc


async def _drain(stream: Optional[asyncio.StreamReader], cap: int) -> bytes:
    kept = bytearray()
    if stream is None:
        return b""
    while chunk := await stream.read(_CHUNK):
        kept += chunk[:max(cap - len(kept), 0)]
    return bytes(kept)


def minimal_env() -> dict:
    keep = ("HOME", "USER", "LOGNAME", "PATH", "SSH_AUTH_SOCK")
    return {k: os.environ[k] for k in keep if k in os.environ}


class SshConn:

    def __init__(self, host: Any, state_dir: Path, *, pinned_fp: Optional[str], ssh_binary: str = ssh_exec.SSH_BINARY,
                 control_dir: Optional[Path] = None, **pool_options: Any) -> None:
        self.host_key: str = host.key
        self._state_dir = Path(state_dir)
        self._pinned_fp = pinned_fp
        self._known_hosts = known_hosts_path(self._state_dir)
        self._pool = SshMasterPool(
            host.key, SshDestination(host.ssh_target, host.ssh_port), login_shell=host.login_shell,
            control_dir=control_dir, instance_tag=instance_tag(self._state_dir), ssh_binary=ssh_binary, max_slots=2,
            pre_options=jobs_pre_options(host.key, self._known_hosts), child_env=minimal_env(), **pool_options)
        self._calls = asyncio.Semaphore(MAX_CALLS_IN_FLIGHT)
        self._connect_lock = asyncio.Lock()

    @property
    def pool(self) -> SshMasterPool:
        return self._pool

    def _require_pin(self) -> None:
        if self._pinned_fp is None:
            raise JobError("host_key_unverified", "the host key of this computer is not confirmed", 409)
        alias = host_alias(self.host_key)
        try:
            text = self._known_hosts.read_text(encoding="ascii", errors="replace")
        except FileNotFoundError:
            text = ""
        lines = [x for x in text.splitlines() if x.strip()]
        if any(_JOBS_LINE_RE.fullmatch(x) is None for x in lines) or sum(x.startswith(alias + " ") for x in lines) != 1:
            raise JobError("host_key_changed", "the jobs known_hosts file is not the pinned one", 409)
        fingerprints = set()
        for line in _pinned_lines(self._known_hosts, alias):
            with contextlib.suppress(JobError):
                fingerprints.add(fingerprint_of(line))
        if self._pinned_fp not in fingerprints:
            raise JobError("host_key_changed", "the host key is not the pinned one", 409)

    @staticmethod
    def _check_failure(failure: Optional[str], stderr: str) -> None:
        if failure in (ssh_exec.FAILURE_HOST_KEY_CHANGED, ssh_exec.FAILURE_HOST_KEY_UNVERIFIED):
            raise JobError("host_key_changed", "the host key is not the pinned one", 409)

    async def _ensure(self) -> None:
        self._require_pin()
        async with self._connect_lock:
            if self._pool.is_up:
                return
            with _transport_errors():
                status = await self._pool.connect()
        if not self._pool.is_up:
            self._check_failure(status.failure, status.detail)
            log.info("ssh_jobs_not_up", host=self.host_key[:12], failure=status.failure, detail=(status.detail or "")[:200])
            raise JobError("unreachable", UNREACHABLE, 503)

    async def call(self, script: bytes, timeout: float) -> ExecResult:
        if not isinstance(script, bytes) or b"\0" in script:
            raise JobError("bad_script", "a far script must be bytes with no NUL byte", 400)
        await self._ensure()
        async with self._calls:
            with _transport_errors():
                result = await self._pool.run(["/bin/sh", "-s"], stdin_data=script, timeout=timeout)
        self._check_failure(result.failure, result.stderr_text)
        return dataclasses.replace(result, stderr=result.stderr[:STDERR_CAP])

    async def _channel(self, argv: List[str]) -> Any:
        await self._ensure()
        with _transport_errors():
            return await self._pool.spawn(argv)

    async def upload(self, path: Path, far_root: str, blob_id: str) -> None:
        _check_token(far_root, _FAR_ROOT_RE, "bad_far_root", forbid_dots=True)
        _check_token(blob_id, _BLOB_ID_RE, "bad_blob_id")
        size = os.stat(path).st_size
        channel = await self._channel(["/bin/sh", "-c", UPLOAD_FAR_SCRIPT, "sh", far_root, blob_id])
        proc = channel.process
        stderr_task = asyncio.create_task(_drain(proc.stderr, STDERR_CAP))

        async def send() -> int:
            try:
                with open(path, "rb") as source:
                    while chunk := await asyncio.to_thread(source.read, _CHUNK):
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    proc.stdin.close()
            return await proc.wait()

        try:
            code = await asyncio.wait_for(send(), _deadline(size))
            err = (await stderr_task).decode("utf-8", "replace")
        except asyncio.TimeoutError:
            raise JobError("far_transfer_failed", "the upload stalled and was stopped", 504) from None
        finally:
            stderr_task.cancel()
            await channel.close()
        self._check_failure(ssh_exec.classify_ssh_failure(err) if code == 255 else None, err)
        if code != 0:
            raise JobError("far_transfer_failed", f"the upload ended with status {code}: {ssh_exec.first_line(err, 200)}", 502)

    async def download(self, far_root: str, job_id: str, size: int, sha256: str, dest: Path) -> None:
        _check_token(far_root, _FAR_ROOT_RE, "bad_far_root", forbid_dots=True)
        _check_token(job_id, _JOB_ID_RE, "bad_job_id")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or _SHA_RE.fullmatch(sha256 or "") is None:
            raise JobError("bad_announcement", "the announced size or sha256 is not valid", 502)
        if size > MAX_DOWNLOAD:
            raise JobError("bundle_too_big", "the result bundle is over the size cap", 413)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            channel = await self._channel(["/bin/sh", "-c", DOWNLOAD_FAR_SCRIPT, "sh", far_root, job_id])
        except BaseException:
            os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                Path(dest).unlink()
            raise
        proc = channel.process
        stderr_task = asyncio.create_task(_drain(proc.stderr, STDERR_CAP))
        digest, got = hashlib.sha256(), 0

        async def receive() -> Tuple[int, str]:
            nonlocal got
            with os.fdopen(fd, "wb") as out:
                while chunk := await asyncio.wait_for(proc.stdout.read(_CHUNK), IDLE_READ_S):
                    got += len(chunk)
                    if got > size or got > MAX_DOWNLOAD:
                        raise JobError("bundle_too_big" if got > MAX_DOWNLOAD else "bundle_size_mismatch",
                                       "the far side sent more than it announced", 502)
                    digest.update(chunk)
                    out.write(chunk)
            return await proc.wait(), (await stderr_task).decode("utf-8", "replace")

        try:
            try:
                code, err = await asyncio.wait_for(receive(), _deadline(size))
            except asyncio.TimeoutError:
                raise JobError("far_transfer_failed", "the download stalled and was stopped", 504) from None
            self._check_failure(ssh_exec.classify_ssh_failure(err) if code == 255 else None, err)
            if code != 0:
                raise JobError("far_transfer_failed", f"the download ended with status {code}: {ssh_exec.first_line(err, 200)}", 502)
            if got != size:
                raise JobError("bundle_size_mismatch", f"the far side sent {got} bytes, not the {size} it announced", 502)
            if digest.hexdigest() != sha256:
                raise JobError("bundle_sha_mismatch", "the downloaded bundle does not match the announced sha256", 502)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                Path(dest).unlink()
            raise
        finally:
            stderr_task.cancel()
            await channel.close()

    async def close(self) -> None:
        await self._pool.disconnect()


def _deadline(size: int) -> float:
    return TRANSFER_BASE_SECONDS + size / TRANSFER_FLOOR_RATE


def _check_token(value: str, pattern: "re.Pattern[str]", code: str, *, forbid_dots: bool = False) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise JobError(code, f"{code.replace('_', ' ')}", 400)
    if forbid_dots and any(part in (".", "..", "") for part in value.split("/")[1:]):
        raise JobError(code, f"{code.replace('_', ' ')}", 400)
