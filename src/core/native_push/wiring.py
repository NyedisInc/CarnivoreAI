
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.config.relay import DEFAULT_RELAY_CONTROL_URL
from src.core.native_push.apns_sender import ApnsSender
from src.core.native_push.key_store import PayloadKeyStore
from src.core.native_push.store import NativeDeviceStore
from src.core.notifications import kind_specs
from src.core.notifications.destinations import secrets as secret_store

logger = structlog.get_logger()

KEY_FIELD = "payload_key"


def store_for(app_state: Any) -> NativeDeviceStore:
    store = getattr(app_state, "native_device_store", None)
    if store is None:
        from src.config import settings

        store = NativeDeviceStore(settings.get_state_dir())
        app_state.native_device_store = store
    return store


def secrets_for(app_state: Any) -> secret_store.DestinationSecrets:
    held = getattr(app_state, "native_push_secrets", None)
    if held is None:
        held = PayloadKeyStore()
        app_state.native_push_secrets = held
    return held


async def delete_key(app_state: Any, row_id: str) -> None:
    try:
        await secrets_for(app_state).delete(row_id)
    except secret_store.SecretError as exc:
        logger.warning("native_push_key_delete_failed", device=row_id, error_type=type(exc).__name__)


async def remove_for_device(app_state: Any, device_id: str) -> int:
    gone = await asyncio.to_thread(store_for(app_state).remove_for_device, device_id)
    for row_id in gone:
        await delete_key(app_state, row_id)
        await drop_local_destination(app_state, row_id)
    return len(gone)


def apns_sender_for(app_state: Any) -> ApnsSender:
    sender = getattr(app_state, "apns_sender", None)
    if sender is None:
        async def session() -> Any:
            manager = getattr(app_state, "phone_link", None)
            return await manager.device_session() if manager is not None and manager.available else None

        async def gone(row_id: str) -> None:
            await drop_local_destination(app_state, row_id)

        manager = getattr(app_state, "phone_link", None)
        sender = ApnsSender(store=store_for(app_state), secrets=secrets_for(app_state), session=session,
                            control_url=manager.control_url if manager is not None else DEFAULT_RELAY_CONTROL_URL,
                            on_gone=gone)
        if manager is not None:
            app_state.apns_sender = sender
    return sender


async def seed_new_device(app_state: Any, row_id: str) -> None:
    from src.core.notifications.destinations.service import get_service

    try:
        await get_service(app_state).destinations.seed_destination_ticks(
            kind_specs.apns_destination_id(row_id), kind_specs.KIND_APNS)
    except (OSError, ValueError) as exc:
        logger.warning("native_push_seed_ticks_failed", error_type=type(exc).__name__)


async def drop_local_destination(app_state: Any, row_id: str) -> None:
    from src.core.notifications.destinations.service import get_service

    try:
        await get_service(app_state).destinations.drop_local_destination(kind_specs.apns_destination_id(row_id))
    except (OSError, ValueError) as exc:
        logger.warning("native_push_drop_ticks_failed", error_type=type(exc).__name__)
