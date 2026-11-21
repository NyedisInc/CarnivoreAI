
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import posixpath
import re
import shlex
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.hosts.ssh_exec import SshArgumentError, posix_quote
from src.core.pack.jobs import paths, recipe
from src.core.pack.jobs.host import _replace_roots
from src.core.pack.jobs.runner import _ANSI
from src.core.pack.jobs.ssh import far_script, readings
from src.core.pack.jobs.ssh.conn import SshConn
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.target import SSH_PREFIX
from src.core.pack.jobs.types import (CAP_JOBS, AdmitBody, CollectAnswer, DepDir, HostState, JobError, ReplyBody, RunStatus, StartBody,
                                      StatusAnswer)
from src.core.pack.transport import blobs

log = structlog.get_logger(__name__)

TIMEOUTS = {"hello": 45.0, "start": 90.0, "stop": 45.0, "seal": 180.0}
DEFAULT_TIMEOUT_S = 30.0
OVERDUE_GRACE_S = 60.0
MAX_CAP_S = 21600
NOT_IN_TIME = "the computer over ssh did not finish in time"
_PLAIN_PATH = re.compile(r"/[A-Za-z0-9._+/-]{1,255}")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FAR_CODES = frozenset({"bad_far_root", "bad_upload", "bad_verb", "bundle_unverified", "git_failed", "job_exists", "missing_tools", "no_bundle",
                       "no_free_slot", "no_such_job", "no_upload", "not_finished", "slot_not_claimed", "start_failed", "still_running"})
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_SHELL = re.compile(r"^/[A-Za-z0-9._/-]{1,100}$")
_FAR_STATES = {"preparing": HostState.PREPARING, "running": HostState.RUNNING, "finishing": HostState.RUNNING}


def _not_here(what: str) -> JobError:
    return JobError("agent_jobs_not_here", f"{what} is not done on a computer reached over ssh", 409)


def _plain_path(text: Optional[str]) -> str:
    if not text or _PLAIN_PATH.fullmatch(text) is None or any(p in (".", "..", "") for p in text.split("/")[1:]):
        raise JobError("far_garbled", "the computer over ssh named a folder this computer will not use", 502)
    return text


def _number(text: Optional[str], default: Optional[int] = None) -> Optional[int]:
    return int(text) if text is not None and text.isdigit() and len(text) <= 12 else default


def setup_key(deps: List[DepDir]) -> str:
    if not deps:
        return ""
    raw = json.dumps(sorted([d.path, d.kind, sorted(d.locks.values()), d.python or ""] for d in deps))
    return hashlib.sha256(raw.encode()).hexdigest()


def _file_size_sha(path: str) -> Tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def steps_script(steps: List[recipe.Step]) -> str:
    out = []
    for step in steps:
        out.append(f"cd {shlex.quote(step.cwd)} || exit 1\n")
        if step.memo_key == "override" and step.argv[1:3] == ["-l", "-c"]:
            text, delim = step.argv[3], "OVERRIDE_" + os.urandom(8).hex()
            out.append(f"{shlex.quote(step.argv[0])} -l -s <<'{delim}'\n{text}\n{delim}\n")
        else:
            out.append(f"{shlex.join(step.argv)}\n")
    return "".join(out)


class SshTarget:

    capabilities: Tuple[str, ...] = (CAP_JOBS,)

    def __init__(self, host_key: str, *, conn: SshConn, store: JobStore, clock: Callable[[], float] = time.time, label: str = "",
                 caller_id: str = "") -> None:
        self.host_key, self.install_id = host_key, SSH_PREFIX + host_key
        self.label = label or host_key[:12]
        self._conn, self._store, self._clock, self._caller = conn, store, clock, caller_id
        self._root: Optional[str] = None
        self._runs: Dict[str, Tuple[float, int]] = {}


    def _row(self) -> Dict[str, Any]:
        return self._store.ssh_target_get(self.host_key) or {}

    def _require_taking(self) -> Dict[str, Any]:
        row = self._row()
        if not row.get("takes_work"):
            raise JobError("pack_restricted", f"{self.label} is not set to take work", 409)
        return row

    async def _far(self, verb: str, values: Optional[Dict[str, str]] = None, *, command: Optional[str] = None, env_sh: Optional[str] = None,
                   steps_sh: Optional[str] = None) -> "far_script.FarAnswer":
        values = dict(values or {})
        configured = self._row().get("far_root")
        if configured and "root" not in values:
            values["root"] = str(configured)
        nonce = far_script.new_nonce()
        try:
            script = far_script.render(verb, values, command=command, env_sh=env_sh, steps_sh=steps_sh, nonce=nonce)
        except far_script.FarScriptError as exc:
            raise JobError("bad_request", f"the request cannot be sent over ssh ({exc.detail})", 422) from exc
        result = await self._conn.call(script, TIMEOUTS.get(verb, DEFAULT_TIMEOUT_S))
        if result.failure is not None:
            raise JobError("unreachable", f"{self.label} did not answer over ssh ({result.failure})", 502)
        raw = result.stdout
        if len(raw) <= far_script.MAX_ANSWER:
            raw = _ANSI.sub("", raw.decode("utf-8", errors="replace")).encode("utf-8")
        answer = far_script.parse(raw, nonce)
        refusal = answer.error
        if refusal is not None:
            code = refusal[0] if refusal[0] in FAR_CODES else "far_error"
            raise JobError("unknown_job" if code == "no_such_job" else code, refusal[1][:256], 404 if code == "no_such_job" else 409)
        if answer.rc != 0:
            raise JobError("far_failed", "the far driver failed", 502)
        return answer

    async def _far_root(self) -> str:
        if self._root is None:
            self._root = _plain_path((await self._far("hello")).fields.get("root"))
        return self._root


    async def admit(self, body: AdmitBody) -> None:
        if body.agent_family is not None:
            raise _not_here("an agent job")
        self._require_taking()
        try:
            self._root = _plain_path((await self._far("hello")).fields.get("root"))
        except JobError as exc:
            self._store.ssh_target_put(self.host_key, last_error=f"{exc.code}: {exc.detail}"[:256])
            raise
        self._store.ssh_target_put(self.host_key, last_ok=self._clock(), last_error=None)

    async def send_bundle(self, path: str) -> str:
        root = await self._far_root()
        blob = os.urandom(16).hex()
        size, sha = await asyncio.to_thread(_file_size_sha, path)
        await self._conn.upload(Path(path), root, blob)
        sealed = await self._far("seal", {"blob": blob, "size": str(size), "sha256": sha})
        if sealed.fields.get("sealed") != str(size):
            raise JobError("far_garbled", "the computer over ssh did not seal the bundle it was sent", 502)
        return blob

    def _shell(self) -> str:
        shell = str(self._row().get("login_shell") or "")
        return shell if _SHELL.fullmatch(shell) else "/bin/sh"

    @staticmethod
    def _checked(body: StartBody) -> str:
        if body.agent is not None or body.command is None:
            raise _not_here("an agent job")
        values = [body.command, *body.env.values(), *(body.setup or [])]
        if any("\0" in v for v in values) or any("\0" in k for k in body.env):
            raise JobError("bad_request", "a command, setup step or variable holds a NUL byte", 422)
        if any(_ENV_KEY.fullmatch(k) is None for k in body.env):
            raise JobError("bad_env_name", "an environment variable name is not valid", 422)
        if body.scope.startswith("/") or ".." in body.scope.split("/"):
            raise JobError("bad_scope", "the scope leaves the job folder", 422)
        return body.command

    async def start(self, body: StartBody) -> str:
        command = self._checked(body)
        self._require_taking()
        root = await self._far_root()
        name = paths.safe_name(posixpath.basename(body.caller_roots[0].rstrip("/")))
        claim = await self._far("claim", {"uid": body.project_uid, "name": name, "job": body.job_id})
        slot = claim.fields.get("slot", "")
        if re.fullmatch(r"[1-9]", slot) is None:
            raise JobError("far_garbled", "the computer over ssh named a folder number this computer will not use", 502)
        folder = f"{root}/folders/{name}-{body.project_uid[:8]}/slot{slot}"
        deps = [DepDir(d.path, d.kind, dict(d.locks), d.python) for d in body.dep_dirs]
        key = setup_key(deps) if body.setup is None and not body.air_gap else ""
        steps = [] if key and claim.fields.get("memo") == key else recipe.plan(folder, deps, {}, body.setup, air_gap=body.air_gap, shell=self._shell())
        steps_sh = steps_script(steps)
        try:
            env_sh = "".join(f"export {k}={posix_quote(v)}\n" for k, v in body.env.items())
        except SshArgumentError as exc:
            raise JobError("bad_request", "a variable value cannot be sent over ssh", 422) from exc
        run_dir = posixpath.join(folder, body.scope) if body.scope else folder
        command_sh = f"cd {shlex.quote(run_dir)} || exit 125\n{_replace_roots(command, body.caller_roots, folder)}\n"
        values = {"uid": body.project_uid, "name": name, "job": body.job_id, "slot": slot, "commit": body.snapshot_commit,
                  "cap": str(body.time_cap_s), "blob": body.snapshot_blob_id}
        if body.est_cpu is not None:
            values["est"] = str(int(body.est_cpu))
        if self._caller:
            values["caller"] = self._caller
        if key:
            values["memo"] = key
        await self._far("start", values, command=command_sh, env_sh=env_sh, steps_sh=steps_sh)
        self._runs[body.job_id] = (self._clock(), body.time_cap_s)
        return "preparing"

    async def status_full(self, job_id: str) -> StatusAnswer:
        await readings.shared(self._store).poll_live_due(self.host_key, readings.Link(self.label, self._conn))
        try:
            far = await self._far("status", {"job": job_id})
        except JobError as exc:
            if exc.code != "unknown_job":
                raise
            return StatusAnswer(state=HostState.MISSING, detail="the job is not on that computer")
        from src.core.mcp.tools import redact_text

        tail = redact_text("\n".join(far.all("out")))
        size = _number(far.fields.get("size"), 0) or 0
        word, reason = far.fields.get("state", ""), far.fields.get("reason") or None
        if word == "exited":
            self._runs.pop(job_id, None)
            code = _number(far.fields.get("code"))
            return StatusAnswer(state=HostState.EXITED, exit_code=code, detail=reason, output_tail=tail, output_bytes=size)
        if word == "lost":
            return StatusAnswer(state=HostState.FAILED, detail="the job ended on the computer over ssh without an exit code (it may have restarted)",
                                output_tail=tail, output_bytes=size)
        if word not in _FAR_STATES:
            raise JobError("far_garbled", "the computer over ssh answered a job state this computer does not know", 502)
        began, cap = self._runs.setdefault(job_id, (self._clock(), MAX_CAP_S))
        if self._clock() - began > cap + OVERDUE_GRACE_S:
            await self._give_up(job_id)
            return StatusAnswer(state=HostState.FAILED, detail=NOT_IN_TIME, output_tail=tail, output_bytes=size)
        return StatusAnswer(state=_FAR_STATES[word], detail=reason, output_tail=tail, output_bytes=size)

    async def _give_up(self, job_id: str) -> None:
        self._runs.pop(job_id, None)
        for verb, values in (("stop", {"job": job_id}), ("release", {"job": job_id})):
            try:
                await self._far(verb, values)
            except JobError as exc:
                log.info("pack_ssh_job_give_up_skipped", verb=verb, code=exc.code)

    async def status(self, job_id: str) -> RunStatus:
        got = await self.status_full(job_id)
        return RunStatus(got.state, got.exit_code, got.detail, got.output_tail, got.output_bytes)

    async def reply(self, body: ReplyBody) -> None:
        raise _not_here("an answer to a worker")

    async def _announced(self, job_id: str) -> Tuple[str, int, Optional[int], str]:
        far = await self._far("collect", {"job": job_id})
        commit = far.fields.get("commit", "")
        if commit and _COMMIT.fullmatch(commit) is None:
            raise JobError("far_garbled", "the computer over ssh announced a result this computer cannot read", 502)
        size, sha = _number(far.fields.get("size")), far.fields.get("sha256", "")
        if commit and (size is None or not sha):
            raise JobError("far_garbled", "the computer over ssh announced a result with no bundle", 502)
        return commit, _number(far.fields.get("changed"), 0) or 0, size, sha

    async def collect(self, job_id: str) -> CollectAnswer:
        commit, changed, _size, _sha = await self._announced(job_id)
        return CollectAnswer(result_commit=commit, blob_id=blobs.new_id() if commit else None, changed=changed)

    async def fetch_result(self, job_id: str, answer: CollectAnswer, state_dir: Path) -> str:
        commit, _changed, size, sha = await self._announced(job_id)
        if not blobs.valid_id(answer.blob_id) or commit != answer.result_commit or size is None:
            raise JobError("result_mismatch", "the computer over ssh no longer announces the result it announced", 502)
        inbox = blobs.Inbox(Path(state_dir) / "pack" / "inbox").directory
        inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest = inbox / f"{answer.blob_id}.blob"
        dest.unlink(missing_ok=True)
        await self._conn.download(await self._far_root(), job_id, size, sha, dest)
        return str(dest)

    async def stop(self, job_id: str, keep_files: bool) -> None:
        await self._far("stop", {"job": job_id})
        self._runs.pop(job_id, None)
        if keep_files:
            await self._far("release", {"job": job_id, "keep": "1"})

    async def release(self, job_id: str) -> None:
        self._runs.pop(job_id, None)
        await self._far("release", {"job": job_id})

    async def install(self, job_id: str, project_uid: str, tools: List[str]) -> List[Dict[str, Any]]:
        raise _not_here("an install")

    async def install_status(self, install_id: str) -> Dict[str, Any]:
        raise _not_here("an install")



_TARGETS: Dict[str, Tuple[Tuple[Any, ...], SshTarget]] = {}


def ssh_target_for(host_key: str) -> SshTarget:
    from src.config import settings
    from src.core.db import connect, db_path_for
    from src.core.hosts import store as hosts_store

    state = Path(settings.get_state_dir())
    try:
        with closing(connect(db_path_for(state), create=False)) as db:
            host = hosts_store.get_host(db, host_key)
    except hosts_store.HostError as exc:
        raise JobError("unreachable", "that computer is not set up over ssh", 502) from exc
    if host.kind != "ssh" or not host.enabled or host.computer_install_id or not host.ssh_target:
        raise JobError("unreachable", "that computer is not an ssh job computer", 502)
    store = JobStore(state)
    row = store.ssh_target_get(host_key) or {}
    signature = (str(state), host.ssh_target, host.ssh_port, host.login_shell, row.get("pinned_fp"))
    held = _TARGETS.get(host_key)
    if held is not None and held[0] == signature:
        return held[1]
    if held is not None:
        try:
            asyncio.get_running_loop().create_task(held[1]._conn.close())
        except RuntimeError:
            log.info("pack_ssh_old_conn_left", host=host_key)
    target = SshTarget(host_key, conn=SshConn(host, state, pinned_fp=row.get("pinned_fp")), store=store, label=host.label)
    _TARGETS[host_key] = (signature, target)
    return target
