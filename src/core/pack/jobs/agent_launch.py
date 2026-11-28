
from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.launch_profiles.permissions import permission_flags
from src.core.pack.jobs import gitio, paths
from src.core.pack.jobs.agent_account import AccountPick
from src.core.pack.jobs.agent_types import (AgentSpec, DEFINITION_KEYS, DEFINITION_QUOTED_MAX, JOB_ID_PATTERN, agents_argument,
                                            definition_fits, valid_model)
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

TASK_DIR = ".carnivore-job"
TASK_FILE = "task.md"
OPENING_PROMPT = (f"Read {TASK_DIR}/{TASK_FILE} and do the work it describes in this folder. Do not push and do not delegate. "
                  "When you are done, end your turn with your result as your last message. "
                  "If you need an answer from the person who asked, ask it as a question.")

_CLAUDE_POSTURE = {"default": "ask", "manual": "ask", "plan": "ask", "acceptEdits": "accept_edits", "bypassPermissions": "skip_all"}
_CODEX_POSTURE = {"ask": "ask", "skip_all": "skip_all"}
_MODE_ONLY = ("auto", "dontAsk")


@dataclass(frozen=True)
class LaunchPlan:

    agent_type: str
    model: Optional[str]
    extra_args: List[str]
    extra_env: Dict[str, str]
    opening_prompt: str
    agent_name: Optional[str] = None
    account_id: Optional[str] = None


@dataclass(frozen=True)
class WorkerRef:

    session_id: str
    session_uuid: str
    tmux_name: str
    epoch: Optional[int]


def worker_tmux_name(session_id: str) -> str:
    from src.core.product_identity import TMUX_SESSION_PREFIX

    return f"{TMUX_SESSION_PREFIX}{session_id}"


def _permission_args(family: str, mode: str) -> List[str]:
    if family == "claude":
        if mode in _MODE_ONLY:
            return ["--permission-mode", mode]
        return list(permission_flags("claude", _CLAUDE_POSTURE[mode]))
    if family == "agy":
        if mode == "skip_all":
            return ["--dangerously-skip-permissions"]
        if mode in ("accept-edits", "auto"):
            return ["--mode", mode]
        return []
    return list(permission_flags("codex", _CODEX_POSTURE[mode])) if mode in _CODEX_POSTURE else []


def _definition(spec: AgentSpec) -> Tuple[Optional[str], Optional[str]]:
    if spec.definition_json is None or spec.agent_type is None:
        return None, None
    body = json.loads(spec.definition_json)
    if not isinstance(body, dict) or set(body) - DEFINITION_KEYS:
        raise JobError("bad_definition", "the agent definition holds a key that is not allowed here", 422)
    model = body.get("model")
    if model is not None and (not isinstance(model, str) or not valid_model(model)):
        raise JobError("bad_definition", "the agent definition names a model this computer will not launch", 422)
    if not definition_fits(spec.agent_type, spec.definition_json):
        raise JobError("definition_too_large", f"the agent definition is too large to start a session with (about {DEFINITION_QUOTED_MAX // 1000} KB once quoted)", 422)
    return agents_argument(spec.agent_type, spec.definition_json), model


def build_launch(spec: AgentSpec, slot: Path, job_id: str, pick: AccountPick) -> LaunchPlan:
    if not re.fullmatch(JOB_ID_PATTERN, job_id):
        raise JobError("bad_launch", "not a job id", 422)
    try:
        spec = AgentSpec.model_validate(spec.model_dump())
    except ValueError as exc:
        raise JobError("bad_launch", f"the launch facts are not allowed: {str(exc)[:200]}", 422) from exc
    args = _permission_args(spec.family, spec.permission_mode)
    definition, def_model = _definition(spec)
    if definition is not None:
        args += ["--agents", definition, "--agent", str(spec.agent_type)]
    env = {**pick.extra_env, **paths.push_block_env(), "CARNIVORE_JOB_ID": job_id}
    return LaunchPlan(agent_type=spec.family, model=def_model or spec.model, extra_args=args, extra_env=env,
                      opening_prompt=OPENING_PROMPT, agent_name=spec.agent_type if definition is not None else None,
                      account_id=pick.account_id)


def _exclude_file(slot: Path) -> Path:
    out = gitio.run(["rev-parse", "--git-path", "info/exclude"], cwd=str(slot)).stdout.decode("utf-8", "replace").strip()
    return (slot / out) if not os.path.isabs(out) else Path(out)


def write_task_file(slot: Path, spec: AgentSpec) -> Path:
    folder = slot / TASK_DIR
    try:
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise JobError("bad_slot", f"{TASK_DIR} in the job folder is not a plain folder", 409)
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        target = folder / TASK_FILE
        if target.is_symlink() or target.exists():
            target.unlink()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(spec.task)
        exclude = _exclude_file(slot)
        line = f"/{TASK_DIR}/"
        have = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if line not in have:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write(("" if not have or exclude.read_text(encoding="utf-8").endswith("\n") else "\n") + line + "\n")
    except OSError as exc:
        raise JobError("bad_slot", f"the task file could not be written ({type(exc).__name__})", 409) from exc
    if stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise JobError("bad_slot", "the task file is not private (mode 0600)", 409)
    return target


CreateWorker = Callable[[LaunchPlan, str, str, str], Awaitable[WorkerRef]]
StopWorker = Callable[..., Awaitable[None]]


def worker_hooks(app: Any) -> Tuple[CreateWorker, StopWorker]:
    from starlette.requests import Request  # noqa: PLC0415

    request = Request({"type": "http", "app": app, "headers": []})

    async def create_worker(plan: LaunchPlan, session_id: str, label: str, working_dir: str) -> WorkerRef:
        from src.api.session_crud_routes import create_session_with_extra
        from src.core.agy.identity import agy_profile_id
        from src.models import CreateSessionRequest

        agent_type = plan.agent_type
        extra_args = list(plan.extra_args)
        model = plan.model
        if agent_type == "agy":
            resolved = agy_profile_id()
            if not resolved:
                raise JobError("no_harness", "no antigravity launch profile is configured on this computer", 409)
            agent_type = resolved
            if model:
                extra_args = ["--model", model, *extra_args]
                model = None
        body = CreateSessionRequest(working_dir=working_dir, agent_type=agent_type, label=label, model=model,
                                    opening_prompt=plan.opening_prompt)
        created = await create_session_with_extra(request, body, agent_extra_args=extra_args, extra_env=dict(plan.extra_env),
                                                  claude_account=plan.account_id, session_id=session_id)
        info = await app.state.session_manager.get_session_info(session_id=created.id)
        if info is None or not info.tmux_session or info.session_row_id is None:
            raise JobError("worker_not_created", "the worker session started but is not listed yet", 503)
        uuid = await asyncio.to_thread(_uuid_of_row, int(info.session_row_id))
        if not uuid:
            raise JobError("worker_not_created", "the worker session has no stored row yet", 503)
        return WorkerRef(created.id, uuid, info.tmux_session, info.session.tmux_created_epoch)

    async def stop_worker(session_id: str, session_uuid: Optional[str] = None) -> None:
        from src.core import session_sleep
        from src.core.session_ops import sleep as sleep_ops

        if session_uuid is None:
            info = await app.state.session_manager.get_session_info(session_id=session_id)
            if info is None or info.session_row_id is None:
                return
            session_uuid = await asyncio.to_thread(_uuid_of_row, int(info.session_row_id))
            if not session_uuid:
                return
        try:
            outcome = await sleep_ops.sleep_session(app.state, session_uuid, fresh_ok=True)
        except sleep_ops.SLEEP_ERRORS as exc:
            raise JobError("worker_not_stopped", f"the worker could not be stopped: {type(exc).__name__}", 409) from exc
        already = (session_sleep.REFUSED_NOT_RUNNING, session_sleep.REFUSED_ARCHIVED, session_sleep.REFUSED_NO_TMUX)
        if outcome.status != "asleep" and outcome.code in already:
            return
        if outcome.status != "asleep":
            raise JobError("worker_not_stopped", outcome.detail or "the worker was not stopped", 409)

    return create_worker, stop_worker


def _uuid_of_row(row_id: int) -> Optional[str]:
    from src.config import settings
    from src.core import session_store
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        return session_store.uuid_for_row(conn, row_id)
