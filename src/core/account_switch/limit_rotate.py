
from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import AbstractSet, Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.config.provider_account_switch import ProviderAccountSwitchConfig, pointer_field
from src.config.provider_accounts import ProviderAccount
from src.core import config_writer, resource_push, session_change_notice
from src.core.account_switch import session_pin, store
from src.core.account_switch.active import effective_active, find_account, pointer_for
from src.core.account_switch.auto_switch import record_switch
from src.core.account_switch.decide import rank_candidates
from src.core.notifications.sources import frames
from src.core.resource_push import topics as resource_topics
from src.core.session_delivery import bring_up
from src.core.session_startup_gate import GATE_READY
from src.models.provider_ledger import AccountUsage
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

PROVIDER = "claude"


class PinUnreadable(Exception):
    """config.json could not be read, so whether a session is pinned is unknown (never read as "no pin")."""

CONTINUE_WORD = "continue"

ROTATED = "limit_rotated"
CONTINUED = "limit_continued"
RESUMED = "limit_resumed"
PINNED = "limit_pinned"
FAILED = "limit_failed"


async def pick_target(
    rows: List[AccountUsage],
    accounts: List[ProviderAccount],
    *,
    capped_id: str,
    threshold: float,
    now: datetime,
    launchable: Callable[[Optional[ProviderAccount]], Awaitable[bool]],
    excluded: AbstractSet[str] = frozenset(),
) -> Optional[str]:
    """The best account other than the capped one that a session can start and resume on, or None.

    Inputs: rows (ledger rows); accounts (configured rows plus the built-in login); capped_id (str);
      threshold (float) - the auto-switch threshold; now (datetime); launchable (async account -> bool);
      excluded (set[str]) - accounts a transcript already proved capped (never moved onto, whatever the ledger says).
    Output: str | None - the account id; None means "nothing has headroom yet".
    Example: await pick_target(rows, accounts, capped_id="a", threshold=99, now=now, launchable=rot.launchable)
    """
    ranked = rank_candidates(
        rows, provider=PROVIDER, active_account_id=capped_id, threshold_percent=threshold, now=now
    )
    for row in ranked:
        if row.id in excluded:
            continue
        if await launchable(find_account(accounts, row.id, PROVIDER)):
            return row.id
    return None


class Rotation:

    def __init__(self, app_state: Any, config_path: Callable[[], Path]) -> None:
        self._app_state = app_state
        self._config_path = config_path

    async def session_uuid(self, info: Any) -> Optional[str]:
        keys = await bring_up.ops_for_app(self._app_state).durable_keys([info])
        key = keys.get(info.session.id)
        return None if key in (None, info.session.id) else key

    async def pin_for(self, session_uuid: Optional[str]) -> Optional[str]:
        """The account this session is pinned to, or None. Inputs: session_uuid. Output: str | None.

        Raises: PinUnreadable - config.json could not be read (unlike ``session_pin.pin_for``, which answers None).
        """
        def read() -> Optional[str]:
            config = config_writer.read_config(self._config_path())
            if not isinstance(config, dict):
                raise ValueError("config.json is not an object")
            return session_pin.read_pins(config).get(session_uuid)

        try:
            return await asyncio.to_thread(read)
        except (FileNotFoundError, ValueError, OSError) as exc:
            logger.warning("limit_rotation_pin_unreadable", error=type(exc).__name__)
            raise PinUnreadable() from exc

    async def launchable(self, account: Optional[ProviderAccount]) -> bool:
        return await asyncio.to_thread(session_pin.is_launchable, account)

    async def move_pointer(
        self, accounts: List[ProviderAccount], switch: ProviderAccountSwitchConfig, from_id: str, to_id: str
    ) -> bool:
        if effective_active(accounts, switch, PROVIDER).account_id != from_id:
            return False
        target = find_account(accounts, to_id, PROVIDER)
        if target is None:
            return False
        try:
            status, _ = await asyncio.to_thread(partial(
                store.set_active, self._config_path(), PROVIDER, pointer_for(target),
                expect={pointer_field(PROVIDER): switch.active_for(PROVIDER), "auto_switch": True},
            ))
        except (FileNotFoundError, ValueError, OSError) as exc:
            logger.warning("limit_rotation_pointer_write_failed", error=type(exc).__name__)
            return False
        if status != config_writer.COMMITTED:
            logger.info("limit_rotation_pointer_superseded")
            return False
        resource_push.notify(resource_topics.ACCOUNT_SWITCH)
        logger.info("limit_rotation_pointer_moved", from_account_id=from_id, to_account_id=to_id)
        return True

    async def wait_ready(self, session_id: str) -> bool:
        ops = bring_up.ops_for_app(self._app_state)
        try:
            await bring_up.wait_ready(
                ops,
                lambda info, _keys: info.session.id == session_id and info.startup_gate == GATE_READY,
                "the restarted session",
            )
        except bring_up.BringUpFailed as exc:
            logger.warning("limit_rotation_not_ready", detail=str(exc))
            return False
        return True

    async def paste_continue(self, info: Any, session_uuid: Optional[str]) -> None:
        from src.api.one_shot_routes import paste_through_gates  # noqa: PLC0415

        request = SimpleNamespace(app=SimpleNamespace(state=self._app_state))
        await paste_through_gates(
            request, info.session.id, CONTINUE_WORD, idle_only=True,
            expected_epoch=info.session.tmux_created_epoch, expected_uuid=session_uuid,
        )

    def notify(
        self, outcome: str, *, session: str, from_account_id: str, to_account_id: str, limit_kind: str,
        moved: bool = False, from_name: str = "", to_name: str = "",
    ) -> None:
        extra: Dict[str, Any] = {"session": session, "limit_kind": limit_kind}
        if outcome == ROTATED and moved:
            record_switch(
                self._app_state, provider=PROVIDER, from_account_id=from_account_id,
                to_account_id=to_account_id, reason=outcome, extra=extra, notify=False,
            )
        else:
            session_change_notice.publish(self._app_state, {
                "type": WSMessageType.PROVIDER_ACCOUNT_SWITCHED, "provider": PROVIDER,
                "from_account_id": from_account_id, "to_account_id": to_account_id, "reason": outcome,
                "at": datetime.now().astimezone().isoformat(), **extra,
            })
        frames.limit_rotation(
            outcome.removeprefix("limit_"), session=session, from_account_id=from_account_id,
            to_account_id=to_account_id, limit_kind=limit_kind, from_name=from_name, to_name=to_name,
        )
