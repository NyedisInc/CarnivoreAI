
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.automations.targets.agent_def import AgentDef

CLAIMED, RUNNING, SUCCEEDED, FAILED, SKIPPED, CANCELLED, WAITING = (
    "claimed", "running", "succeeded", "failed", "skipped", "cancelled", "waiting_on_you")
LIVE_STATUSES = (CLAIMED, RUNNING, WAITING)

R_MISSED, R_DISABLED, R_TWO_RUNNING, R_PREV_RUNNING = "missed_slot", "disabled", "two_runs_running", "previous_run_still_running"
R_PAUSED = "scheduler_paused"
R_LOGIN, R_USAGE, R_REFRESH = "login_needs_attention", "usage_over_90", "refresh_in_flight"
R_TARGET_MISSING, R_INTERRUPTED, R_TARGET_INVALID = "target_missing", "interrupted", "target_invalid"

GRACE_S = 120.0
MIN_INTERVAL_S = 900.0
MAX_LIVE_RUNS = 2
RUNS_KEPT = 200
REPORT_CAP_BYTES = 1 << 20
REPORTS_TOTAL_CAP_BYTES = 32 << 20

TARGET_KINDS = ("blueprint_launch", "recipe", "swarm_card", "agent", "session_message", "command", "sequence")
SEQUENCE_MAX_STEPS = 4
SEQUENCE_STEP_KINDS = ("command", "recipe")
SEQUENCE_LAST_KINDS = ("command", "recipe", "session_message", "agent", "blueprint_launch")
RECIPES = ("scrooge",)
SYSTEM_ACTIONS = ("sleep_idle_sessions", "restart_session", "send_notification",
                  "backup_health_check")


class AutomationInvalid(ValueError):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class AutomationNotFound(LookupError):
    pass


class RevisionConflict(Exception):
    pass


class ReportTooLarge(ValueError):
    pass


class Delivery(BaseModel):

    model_config = ConfigDict(extra="forbid")
    notify: bool = True
    notify_on: Optional[Literal["always", "failure", "report"]] = None


class BlueprintTarget(BaseModel):
    """Start a saved Blueprint. ``members`` None means all of them."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["blueprint_launch"]
    blueprint_uuid: str = Field(min_length=1, max_length=80)
    members: Optional[List[int]] = None

    @field_validator("members")
    @classmethod
    def _indexes(cls, value: Optional[List[int]]) -> Optional[List[int]]:
        if value is not None and (any(i < 0 for i in value) or len(set(value)) != len(value)):
            raise ValueError("member indexes must be unique and non-negative")
        return value


class RecipeTarget(BaseModel):
    """Run a report recipe or a named system action (``SYSTEM_ACTIONS``); each owns its params model, checked at save."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["recipe"]
    recipe: Literal["scrooge", "sleep_idle_sessions", "restart_session", "send_notification",
                    "backup_health_check"]
    params: Dict[str, Any] = Field(default_factory=dict)


class CardTarget(BaseModel):
    """Deal one Swarm card; caps follow ``ops.create`` after the ``{date}`` / ``{week}`` expansion (S9 checks them)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["swarm_card"]
    project_id: int
    title: str = Field(min_length=1)
    summary: str = Field(max_length=200)
    text: str = ""
    how_to_validate: str = ""
    queued: bool = False


class SessionMessageTarget(BaseModel):

    model_config = ConfigDict(extra="forbid")
    kind: Literal["session_message"]
    session_uuid: str = Field(min_length=8, max_length=80, pattern=r"^[0-9A-Za-z-]+$")
    text: str = Field(min_length=1, max_length=20000)
    if_asleep: Literal["wake", "skip"] = "wake"
    if_gone: Literal["start", "fail"] = "start"
    project_id: Optional[int] = Field(default=None, ge=1)
    session_name: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def _start_needs_a_project(self) -> "SessionMessageTarget":
        if self.if_gone == "start" and self.project_id is None:
            raise ValueError("if_gone start needs project_id")
        return self


class CommandTarget(BaseModel):

    model_config = ConfigDict(extra="forbid")
    kind: Literal["command"]
    command: str = Field(min_length=1, max_length=500)
    project_id: Optional[int] = Field(default=None, ge=1)


class SequenceTarget(BaseModel):
    """Two to four steps in order (``targets/sequence.py``); each step is checked against its own kind's model."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["sequence"]
    steps: List[Dict[str, Any]] = Field(min_length=2, max_length=SEQUENCE_MAX_STEPS)

    @field_validator("steps")
    @classmethod
    def _step_kinds(cls, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for index, step in enumerate(steps):
            allowed = SEQUENCE_LAST_KINDS if index == len(steps) - 1 else SEQUENCE_STEP_KINDS
            kind = step.get("kind") if isinstance(step, dict) else None
            if kind not in allowed:
                raise ValueError(f"step {index + 1} may not be {kind!r} (allowed: {', '.join(allowed)})")
        return steps


_TARGET_MODELS = {"blueprint_launch": BlueprintTarget, "recipe": RecipeTarget, "swarm_card": CardTarget, "agent": AgentDef,
                  "session_message": SessionMessageTarget, "command": CommandTarget, "sequence": SequenceTarget}


def validate_target(raw: Any) -> Dict[str, Any]:
    kind = raw.get("kind") if isinstance(raw, dict) else None
    model = _TARGET_MODELS.get(kind)
    if model is None:
        raise AutomationInvalid("target_invalid", f"unknown target kind {kind!r}")
    try:
        clean = model.model_validate(raw).model_dump(mode="json")
    except ValueError as exc:
        raise AutomationInvalid("target_invalid", str(exc)[:300]) from exc
    if kind == "sequence":
        clean["steps"] = [validate_target(step) for step in clean["steps"]]
        return clean
    if kind == "agent" and clean.get("login_account_id"):
        from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415
        from src.core.byoai.native import cli_run  # noqa: PLC0415

        try:
            cli_run.profile_dir("claude", clean["login_account_id"])
        except ByoaiError as exc:
            raise AutomationInvalid("target_invalid", "no such claude login in the provider ledger") from exc
    return clean


def validate_delivery(raw: Any) -> Dict[str, Any]:
    try:
        return Delivery.model_validate(raw or {}).model_dump(mode="json")
    except ValueError as exc:
        raise AutomationInvalid("delivery_invalid", str(exc)[:300]) from exc


class RunOutcome(BaseModel):
    """What a target runner returns; the scheduler writes it onto the run.

    ``status`` is ``succeeded``, ``failed``, ``skipped``, ``cancelled`` or (a run that goes on without the runner, such as a
    Blueprint's sessions) ``running`` / ``waiting_on_you``, which leaves the run live.
    """

    status: str = SUCCEEDED
    reason: Optional[str] = None
    report: Optional[Dict[str, Any]] = None
    cost_usd: Optional[float] = None
    usage: Optional[Dict[str, int]] = None
    sessions: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
