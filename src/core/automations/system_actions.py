
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.core.automations.recipes import RecipeFailed, RecipeSkipped
from src.core.session_status import STATUS_DEAD

logger = structlog.get_logger()

NOTIFY_TEXT_MAX = 280
R_SLEEPER_OFF, R_SESSION_LIVE, R_RESTART_REFUSED = "auto_sleep_unavailable", "session_live", "restart_refused"


class NoParams(BaseModel):
    """An action that takes no parameters."""

    model_config = ConfigDict(extra="forbid")


class RestartParams(BaseModel):
    """Which stopped session to bring back, by its durable ``session_uuid``."""

    model_config = ConfigDict(extra="forbid")
    session_uuid: str = Field(min_length=8, max_length=80, pattern=r"^[0-9A-Za-z-]+$")


class NotifyParams(BaseModel):
    """The notification's text (redacted before it is sent)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=NOTIFY_TEXT_MAX)


async def sleep_idle_sessions(ctx: Any, params: NoParams) -> Tuple[Dict[str, Any], Optional[float]]:
    sleeper = getattr(ctx.app_state, "auto_sleeper", None)
    if sleeper is None:
        raise RecipeFailed(R_SLEEPER_OFF)
    slept = await sleeper.pass_once()
    return {"action": "sleep_idle_sessions", "slept": len(slept)}, None


async def restart_session(ctx: Any, params: RestartParams) -> Tuple[Dict[str, Any], Optional[float]]:
    from src.core.session_delivery import bring_up  # noqa: PLC0415
    from src.core.session_ops import restart as restart_ops  # noqa: PLC0415

    live = await bring_up.find_live(bring_up.ops_for_app(ctx.app_state), params.session_uuid)
    if live is not None and live.activity_status != STATUS_DEAD:
        raise RecipeSkipped(R_SESSION_LIVE)
    try:
        answer = await restart_ops.restart_stopped_session(ctx.app_state, params.session_uuid)
    except restart_ops.RESTART_ERRORS as exc:
        logger.info("automation_restart_refused", error_type=type(exc).__name__)
        raise RecipeFailed(R_RESTART_REFUSED) from exc
    body = answer.model_dump(mode="json") if hasattr(answer, "model_dump") else dict(answer or {})
    return {"action": "restart_session", "conversation": body.get("conversation"), "row_reused": body.get("row_reused")}, None


async def send_notification(ctx: Any, params: NotifyParams) -> Tuple[Dict[str, Any], Optional[float]]:
    from src.core.automations.targets.recipe import tell_notice  # noqa: PLC0415
    from src.core.timers.redact import redact  # noqa: PLC0415

    return {"action": "send_notification", "sent": tell_notice(redact(params.text))}, None


async def backup_health_check(ctx: Any, params: NoParams) -> Tuple[Dict[str, Any], Optional[float]]:
    from src.core.backup_health import runner  # noqa: PLC0415
    from src.core.pipeline import triggers  # noqa: PLC0415

    state_dir, db_path = triggers.default_paths()
    outcome = await asyncio.to_thread(runner.run_checks, state_dir, db_path)
    return {"action": "backup_health_check", "alerts": outcome}, None


REGISTRY: Dict[str, Any] = {
    "sleep_idle_sessions": (NoParams, sleep_idle_sessions),
    "restart_session": (RestartParams, restart_session),
    "send_notification": (NotifyParams, send_notification),
    "backup_health_check": (NoParams, backup_health_check),
}
