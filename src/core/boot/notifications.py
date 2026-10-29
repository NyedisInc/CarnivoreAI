
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import structlog

from src.config import settings
from src.core import claude_hooks
from src.core.boot.steps import BootStep, FailureMode, teardown_slot
from src.core.notifications import install as notifications_install
from src.core.session_notification_policy import (
    NotificationPolicyStore,
    hydrate_from_datastore as hydrate_notification_policy,
)

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


@dataclass
class _PipelineHandle:

    installed: Optional[object] = None


def _pipeline_steps() -> list[BootStep]:
    held = _PipelineHandle()

    async def start(ctx: "BootContext") -> None:
        from src.core.db import db_path_for as _db_path_for

        ctx.notification_policy_store = NotificationPolicyStore()
        hydrate_notification_policy(ctx.notification_policy_store, _db_path_for(settings.get_state_dir()))
        ctx.session_manager.attach_notification_policy_store(ctx.notification_policy_store)
        held.installed = await notifications_install.install(ctx.app.state, ctx.session_manager)

    async def stop(_ctx: "BootContext") -> None:
        await notifications_install.uninstall(held.installed)

    return [BootStep(name="notifications", order=140, start=start, stop=stop, stop_order=teardown_slot(47))]


def _strip_hooks(_ctx: "BootContext") -> None:
    claude_hooks.strip_managed_hooks(claude_hooks.default_settings_path())


def steps() -> list[BootStep]:
    return [
        *_pipeline_steps(),
        BootStep(name="claude_hooks_strip", order=150, start=_strip_hooks, failure=FailureMode.DEGRADED,
                 degrades_on=(Exception,), failure_event="claude_hooks_strip_failed",
                 swallow_reason="server boot is never blocked by a settings-file glitch; the strip is retried next boot"),
    ]
