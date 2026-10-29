
from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.notifications import contracts, engine as engine_mod, links, routing_view
from src.core.notifications.destinations import migration, switch_origin, tick_backfill
from src.core.notifications.destinations.service import NotificationService, get_service
from src.core.notifications.kinds import apns, registry, webpush
from src.core.notifications.sources import open_checks

log = structlog.get_logger(__name__)


@dataclass
class Installed:

    engine: Optional[engine_mod.NotifyEngine] = None
    service: Optional[NotificationService] = None
    migration: Optional[migration.MigrationResult] = None


def _computer_name() -> str:
    return platform.node().split(".")[0][:64] or "this computer"


def _subscription_ids(app_state: Any) -> list[str]:
    from src.core.web_push.wiring import sender_for  # noqa: PLC0415

    try:
        return [str(r["id"]) for r in sender_for(app_state).store.list() if r.get("id")]
    except (OSError, ValueError, KeyError):
        log.warning("notification_install_subscriptions_unreadable")
        return []


async def _run_migration(app_state: Any, service: NotificationService) -> Optional[migration.MigrationResult]:
    from src.config import settings  # noqa: PLC0415

    try:
        return await migration.migrate(
            Path(settings.auth_config_file).expanduser(), service.docs, service.destinations,
            _subscription_ids(app_state), writer=service.routing,
        )
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        log.warning("notification_migration_failed", error_type=type(exc).__name__)
        return None


async def install(app_state: Any, manager: Any) -> Installed:
    installed = Installed()
    try:
        from src.config import settings  # noqa: PLC0415
        from src.core.mcp import pending  # noqa: PLC0415
        from src.core.native_push.wiring import apns_sender_for  # noqa: PLC0415
        from src.core.web_push.wiring import sender_for  # noqa: PLC0415

        service = get_service(app_state)
        installed.service = service
        routing_view.install_routing(service.routing.view, service.routing)
        webpush.install_push_sender(lambda: sender_for(app_state))
        apns.install_apns_sender(lambda: apns_sender_for(app_state))
        installed.migration = await _run_migration(app_state, service)
        await switch_origin.backfill(service.docs, service.secrets)
        await tick_backfill.backfill_type_ticks(service.docs)

        async def link_base() -> str:
            return (await links.resolver.resolve(getattr(app_state, "phone_link", None))).base

        engine = engine_mod.NotifyEngine(
            sender_lookup=registry.sender_for,
            is_muted=lambda session_id: bool(manager.notification_policy_for(session_id).suppresses),
            is_uuid_muted=lambda session_uuid: bool(manager.notification_policy_for_uuid(session_uuid).suppresses),
            secrets_lookup=service.secrets.get,
            sms_state_dir=settings.get_state_dir(),
            link_base=link_base,
            computer_name=_computer_name,
        )
        await engine.start()
        installed.engine = engine
        engine_mod.install_engine(engine)
        open_checks.register_open_checks(
            engine, lambda: getattr(app_state, "attention_watcher", None), pending.get_store)
        contracts.install_sink(engine.offer)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        log.warning("notification_install_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        await uninstall(installed)
        installed.engine = None
    return installed


async def uninstall(installed: Optional[Installed]) -> None:
    contracts.uninstall_sink()
    engine_mod.install_engine(None)
    routing_view.uninstall_routing()
    webpush.install_push_sender(None)
    apns.install_apns_sender(None)
    if installed is not None and installed.engine is not None:
        await installed.engine.stop()
