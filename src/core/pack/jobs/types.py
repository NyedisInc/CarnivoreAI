
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import Field, field_validator, model_validator

from src.core.pack.errors.input_error import PackInputError
from src.core.pack.jobs.agent_types import (ACCOUNT_KEY_PATTERN, CAP_AGENT, JOB_ID_PATTERN, AgentSpec, ReplyBody, UsageTotals,  # noqa: F401
                                            _Wire)

CAP_JOBS = "pack.jobs"
CAP_NEEDS = "pack.jobs.needs"

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class JobError(Exception):

    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


class JobState(str, Enum):

    PLACING = "placing"
    HERE = "here"
    WAITING_APPROVAL = "waiting_approval"
    MIRRORING = "mirroring"
    STARTING = "starting"
    RUNNING = "running"
    COLLECTING = "collecting"
    LANDING = "landing"
    DONE = "done"
    FAILED = "failed"
    LOST = "lost"
    STOPPED = "stopped"
    QUESTION = "question"
    REFUSED = "refused"


TERMINAL = {JobState.HERE, JobState.DONE, JobState.FAILED, JobState.LOST, JobState.STOPPED, JobState.REFUSED}


class HostState(str, Enum):

    PREPARING = "preparing"
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    STOPPED = "stopped"
    MISSING = "missing"
    PARKED = "parked"


@dataclass
class DepDir:

    path: str
    kind: Literal["npm", "venv"]
    locks: Dict[str, str] = field(default_factory=dict)
    python: Optional[str] = None


@dataclass
class Snapshot:

    commit: str
    tree: str
    head: Optional[str]
    toplevel: str
    scope: str
    side_git_dir: str
    dep_dirs: List[DepDir] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    outside_links: List[str] = field(default_factory=list)
    new_bytes: int = 0
    taken_at: float = 0.0


def _relative_ok(value: str) -> bool:
    return not value.startswith("/") and ".." not in value.replace("\\", "/").split("/") and "\0" not in value


@dataclass
class JobRequest:

    command: str
    folder: str
    kind: str = "suite"
    caller_session: Optional[str] = None
    outputs: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    time_cap_s: int = 3600
    est_cpu: Optional[float] = None
    est_ram_gb: Optional[float] = None
    needs: List[str] = field(default_factory=list)
    prefer: List[str] = field(default_factory=list)

    def validate(self) -> None:
        from src.core.pack.placement import workload

        def bad(why: str) -> JobError:
            return JobError("bad_request", why, 422)

        if not self.folder.startswith("/"):
            raise bad("the folder must be an absolute path")
        if self.kind not in workload.DEFAULTS:
            raise bad(f"kind must be one of {', '.join(workload.DEFAULTS)}")
        if not 1 <= self.time_cap_s <= 21600:
            raise bad("time_cap_s must be between 1 and 21600")
        if not 1 <= len(self.command) <= 20000 or "\0" in self.command:
            raise bad("the command must be 1 to 20000 characters")
        if len(self.outputs) > 50 or not all(o and _relative_ok(o) for o in self.outputs):
            raise bad("outputs: at most 50 relative paths with no ..")
        if len(self.env) > 64:
            raise bad("env: at most 64 variables")
        from src.core.pack.placement import needs as needs_mod

        for word_list in (self.needs, self.prefer):
            try:
                needs_mod.parse_all(word_list)
            except ValueError as exc:
                raise bad(str(exc)) from exc
        for key, value in self.env.items():
            if not _ENV_KEY.match(key) or len(value) > 8192 or "\0" in value:
                raise bad(f"env variable {key[:20]!r} is not allowed")


@dataclass
class PlaceAnswer:

    decision: Literal["here", "remote", "refused"]
    peer_install_id: Optional[str]
    peer_label: Optional[str]
    reason: str
    why: List[dict] = field(default_factory=list)
    code: Optional[str] = None
    install: List[str] = field(default_factory=list)


@dataclass
class RunStatus:

    state: HostState
    exit_code: Optional[int] = None
    detail: Optional[str] = None
    output_tail: str = ""
    output_bytes: int = 0


@dataclass
class Collected:

    result_commit: str
    changed: int
    bundle_path: str


@dataclass
class LandResult:

    applied: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    clashes: List[str] = field(default_factory=list)
    ref: Optional[str] = None
    dropped: List[str] = field(default_factory=list)


@dataclass
class JobRecord:

    id: str
    idem_key: str = ""
    project_uid: str = ""
    project_name: str = ""
    caller_session: Optional[str] = None
    request_json: str = "{}"
    state: JobState = JobState.PLACING
    peer_install_id: Optional[str] = None
    peer_label: Optional[str] = None
    reason: Optional[str] = None
    scope: Optional[str] = None
    snapshot_commit: Optional[str] = None
    snapshot_tree: Optional[str] = None
    snapshot_at: Optional[float] = None
    result_commit: Optional[str] = None
    exit_code: Optional[int] = None
    output_tail: Optional[str] = None
    land_json: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    body: str = "command"
    task_head: Optional[str] = None
    agent_type: Optional[str] = None
    family: Optional[str] = None
    permission_mode: Optional[str] = None
    account_label: Optional[str] = None
    account_how: Optional[str] = None
    result_text: Optional[str] = None
    question: Optional[str] = None
    question_kind: Optional[str] = None
    usage_json: Optional[str] = None
    notified_state: Optional[str] = None
    worker_session_uuid: Optional[str] = None


@dataclass
class HostJob:

    job_id: str
    caller_install: str = ""
    project_uid: str = ""
    state: HostState = HostState.PREPARING
    slot_path: Optional[str] = None
    snapshot_commit: Optional[str] = None
    result_commit: Optional[str] = None
    result_blob_id: Optional[str] = None
    exit_code: Optional[int] = None
    time_cap_s: int = 3600
    keep_until: Optional[float] = None
    detail: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    body: str = "command"
    worker_session_id: Optional[str] = None
    worker_session_uuid: Optional[str] = None
    worker_tmux: Optional[str] = None
    worker_epoch: Optional[int] = None
    family: Optional[str] = None
    permission_mode: Optional[str] = None
    account_label: Optional[str] = None
    account_how: Optional[str] = None
    parked_at: Optional[float] = None
    question: Optional[str] = None
    question_kind: Optional[str] = None
    result_text: Optional[str] = None
    usage_json: Optional[str] = None
    replied_at: Optional[float] = None


def _check_relative(value: str) -> str:
    if not _relative_ok(value):
        raise PackInputError("must be a relative path with no ..")
    return value


class AdmitBody(_Wire):

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    project_uid: str = Field(min_length=8, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    est_cpu: Optional[float] = Field(default=None, ge=0, le=1024)
    est_ram_gb: Optional[float] = Field(default=None, ge=0, le=65536)
    omit_when_none: ClassVar[Tuple[str, ...]] = ("agent_family", "account_key", "needs")
    agent_family: Optional[Literal["claude", "codex"]] = None
    account_key: Optional[str] = Field(default=None, pattern=ACCOUNT_KEY_PATTERN)
    needs: Optional[List[str]] = Field(default=None, max_length=24)

    @field_validator("needs")
    @classmethod
    def _needs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        from src.core.pack.placement import needs as needs_mod

        if v is not None:
            needs_mod.parse_all(v, limit=24)
        return v


class DepDirWire(_Wire):

    path: str = Field(min_length=1, max_length=512)
    kind: Literal["npm", "venv"]
    locks: Dict[str, str] = Field(default_factory=dict, max_length=20)
    python: Optional[str] = Field(default=None, max_length=32)

    @field_validator("path")
    @classmethod
    def _rel(cls, v: str) -> str:
        return _check_relative(v)


class StartBody(_Wire):

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    project_uid: str = Field(min_length=8, max_length=64)
    snapshot_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    snapshot_blob_id: str = Field(min_length=1, max_length=128)
    scope: str = Field(default="", max_length=512)
    dep_dirs: List[DepDirWire] = Field(default_factory=list, max_length=20)
    omit_when_none: ClassVar[Tuple[str, ...]] = ("command", "agent")
    command: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    agent: Optional[AgentSpec] = None
    kind: str = Field(min_length=1, max_length=32)
    est_cpu: Optional[float] = Field(default=None, ge=0, le=1024)
    est_ram_gb: Optional[float] = Field(default=None, ge=0, le=65536)
    env: Dict[str, str] = Field(default_factory=dict, max_length=64)
    outputs: List[str] = Field(default_factory=list, max_length=100)
    time_cap_s: int = Field(default=3600, ge=1, le=21600)
    caller_roots: List[str] = Field(min_length=1, max_length=4)
    setup: Optional[List[str]] = Field(default=None, max_length=10)
    air_gap: bool = False

    @model_validator(mode="after")
    def _one_body(self) -> "StartBody":
        if (self.command is None) == (self.agent is None):
            raise PackInputError("send exactly one of command and agent")
        return self

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        return _check_relative(v) if v else v

    @field_validator("outputs")
    @classmethod
    def _outputs(cls, v: List[str]) -> List[str]:
        return [_check_relative(o) for o in v]

    @field_validator("env")
    @classmethod
    def _env(cls, v: Dict[str, str]) -> Dict[str, str]:
        for key, value in v.items():
            if not _ENV_KEY.match(key) or len(value) > 8192 or "\0" in value:
                raise PackInputError("env variable name or value not allowed")
        return v

    @field_validator("caller_roots")
    @classmethod
    def _roots(cls, v: List[str]) -> List[str]:
        if not all(r.startswith("/") and "\0" not in r for r in v):
            raise PackInputError("caller_roots must be absolute paths")
        return v

    @field_validator("setup")
    @classmethod
    def _setup(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and any(not s or len(s) > 2000 or "\0" in s for s in v):
            raise PackInputError("each setup step is 1 to 2000 characters")
        return v


class JobIdBody(_Wire):

    job_id: str = Field(pattern=JOB_ID_PATTERN)


class StopBody(_Wire):

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    keep_files: bool = False


class StatusAnswer(_Wire):
    omit_when_none: ClassVar[Tuple[str, ...]] = ("result_text", "question", "question_kind", "usage", "account_label", "account_how",
                                                 "worker_session_uuid")

    state: HostState
    exit_code: Optional[int] = None
    detail: Optional[str] = None
    output_tail: str = ""
    output_bytes: int = 0
    result_text: Optional[str] = Field(default=None, max_length=16384)
    question: Optional[str] = Field(default=None, max_length=16384)
    question_kind: Optional[Literal["question", "plan_approval", "input", "permission", "startup"]] = None
    usage: Optional[UsageTotals] = None
    account_label: Optional[str] = Field(default=None, max_length=200)
    account_how: Optional[Literal["same", "relay", "local", "fallback"]] = None
    worker_session_uuid: Optional[str] = Field(default=None, max_length=64)


class CollectAnswer(_Wire):
    omit_when_none: ClassVar[Tuple[str, ...]] = ("result_text", "question", "question_kind", "usage", "account_label", "account_how",
                                                 "worker_session_uuid")

    result_commit: str = Field(default="", pattern=r"^([0-9a-f]{40,64})?$")
    blob_id: Optional[str] = None
    changed: int = 0
    result_text: Optional[str] = Field(default=None, max_length=16384)
    question: Optional[str] = Field(default=None, max_length=16384)
    question_kind: Optional[Literal["question", "plan_approval", "input", "permission", "startup"]] = None
    usage: Optional[UsageTotals] = None
    account_label: Optional[str] = Field(default=None, max_length=200)
    account_how: Optional[Literal["same", "relay", "local", "fallback"]] = None
    worker_session_uuid: Optional[str] = Field(default=None, max_length=64)
