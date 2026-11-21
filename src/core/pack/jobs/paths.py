
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Dict

from src.core.pack.carry.worktree import in_cloud_sync
from src.core.pack.jobs.types import JobError

JOBS_TMUX_SOCKET = "carnivore-jobs"

_UID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_JOB_ID = re.compile(r"^job_[0-9a-f]{12}$")


def default_jobs_root() -> Path:
    env = os.environ.get("CARNIVORE_JOBS_ROOT")
    return Path(env) if env else Path.home() / ".carnivore" / "jobs"


CLEAN_ENV_KEYS = ("HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "TERM")


def clean_env(*, path: str = "/usr/bin:/bin:/usr/sbin:/sbin") -> dict:
    env = {k: os.environ[k] for k in CLEAN_ENV_KEYS if k in os.environ}
    env["PATH"] = path
    return env


def check_root(root: Path) -> Path:
    given = os.path.abspath(os.fspath(root))
    real = os.path.realpath(given)
    if in_cloud_sync(given) or in_cloud_sync(real):
        raise JobError("jobs_root_in_cloud", "the jobs folder is inside a cloud-sync folder, which would sync dependency folders", 409)
    Path(real).mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(real, 0o700)
    return Path(real)


def _uid(project_uid: str) -> str:
    if not _UID.match(project_uid):
        raise JobError("bad_uid", "the project id is not valid", 422)
    return project_uid


def _job_id(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise JobError("bad_job_id", "the job id is not valid", 422)
    return job_id


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip(".")[:40].strip("_")
    return cleaned or "project"


def new_job_id() -> str:
    return "job_" + secrets.token_hex(6)


def side_repo_dir(root: Path, project_uid: str) -> Path:
    return Path(root) / "repos" / f"{_uid(project_uid)}.git"


def slot_dir(root: Path, project_name: str, project_uid: str, n: int) -> Path:
    return Path(root) / "folders" / f"{safe_name(project_name)}-{_uid(project_uid)[:8]}" / f"slot{int(n)}"


def meta_dir(root: Path, job_id: str) -> Path:
    path = Path(root) / "meta" / _job_id(job_id)
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def session_name(job_id: str) -> str:
    return "cvjob_" + _job_id(job_id)[4:]


_NO_PUSH_PREFIXES = ("https://", "git@", "ssh://", "http://", "git://", "file://")


def push_block_env() -> Dict[str, str]:
    env = {"GIT_CONFIG_COUNT": str(len(_NO_PUSH_PREFIXES))}
    for i, prefix in enumerate(_NO_PUSH_PREFIXES):
        env[f"GIT_CONFIG_KEY_{i}"] = "url.carnivore-no-push://.pushInsteadOf"
        env[f"GIT_CONFIG_VALUE_{i}"] = prefix
    return env
