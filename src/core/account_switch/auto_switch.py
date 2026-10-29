
from __future__ import annotations

import asyncio
from dataclasses import asdict
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

from src.config.provider_account_switch import ProviderAccountSwitchConfig, pointer_field
from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core import config_writer, resource_push, session_change_notice
from src.core.notifications.sources import frames
from src.core.resource_push import topics as resource_topics
from src.core.account_switch import profile_setup, shared_links, store
from src.core.account_switch.active import PROVIDERS, effective_active, find_account, pointer_for
from src.core.account_switch.decide import SwitchDecision, decide_switch
from src.core.provider_ledger import accounts_store, poller_scan
from src.models.provider_ledger import LedgerSnapshot
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

_LAST_SWITCH: Optional[Dict[str, Any]] = None


def last_switch() -> Optional[Dict[str, Any]]:
    return dict(_LAST_SWITCH) if _LAST_SWITCH is not None else None


def record_switch(
    app_state: Any,
    *,
    provider: str,
    from_account_id: Optional[str],
    to_account_id: str,
    reason: str,
    window_kind: Optional[str] = None,
    used_pct: Optional[float] = None,
    window_seconds: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    notify: bool = True,
) -> Dict[str, Any]:
    global _LAST_SWITCH
    entry = {
        "provider": provider,
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "reason": reason,
        "window_kind": window_kind,
        "used_pct": used_pct,
        "window_seconds": window_seconds,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _LAST_SWITCH = entry
    try:
        from src.core.stats import events
        events.record_soon("account_switched", str(to_account_id), {
            "provider": provider, "from": from_account_id, "reason": reason})
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats_event_hook_failed", error_type=type(exc).__name__)
    session_change_notice.publish(
        app_state,
        {"type": WSMessageType.PROVIDER_ACCOUNT_SWITCHED, **entry, **(extra or {})},
    )
    resource_push.notify(resource_topics.ACCOUNT_SWITCH)
    if notify:
        frames.account_switched(entry)
    return entry


def _default_config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def _linkable(account: Optional[ProviderAccount]) -> bool:
    if account is None:
        return False
    if shared_links.is_default_profile(account.provider, profile_dir_for(account)):
        return True
    if not profile_setup.setup_done(account):
        return False
    report = shared_links.ensure_shared_links(
        profile_dir_for(account), account.provider, managed=account.managed
    )
    return report.resume_safe


def plan_switches(
    snapshot: LedgerSnapshot,
    accounts: List[ProviderAccount],
    switch: ProviderAccountSwitchConfig,
    *,
    now: datetime,
    linkable: Callable[[Optional[ProviderAccount]], bool] = _linkable,
) -> List[SwitchDecision]:
    if not switch.auto_switch:
        return []
    decisions: List[SwitchDecision] = []
    for provider in PROVIDERS:
        active = effective_active(accounts, switch, provider)
        excluded: Set[str] = set()
        while True:
            rows = [row for row in snapshot.accounts if row.id not in excluded]
            decision = decide_switch(
                rows,
                provider=provider,
                active_account_id=active.account_id,
                threshold_percent=switch.threshold_percent,
                now=now,
            )
            if decision is None:
                break
            if linkable(find_account(accounts, decision.to_account_id, provider)):
                decisions.append(decision)
                break
            excluded.add(decision.to_account_id)
    return decisions


def _pointer_of_decision(
    accounts: List[ProviderAccount], decision: SwitchDecision
) -> Optional[str]:
    target = find_account(accounts, decision.to_account_id, decision.provider)
    return pointer_for(target) if target is not None else decision.to_account_id


async def after_pass(
    snapshot: LedgerSnapshot,
    app_state: Any = None,
    *,
    config_path: Callable[[], Path] = _default_config_path,
    read_switch: Callable[[Path], ProviderAccountSwitchConfig] = store.read_switch,
    list_accounts: Callable[[Path], List[ProviderAccount]] = accounts_store.list_accounts,
    set_active: Callable[..., Any] = store.set_active,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> List[SwitchDecision]:
    path = config_path()
    try:
        switch = await asyncio.to_thread(read_switch, path)
        if not switch.auto_switch:
            return []
        accounts = poller_scan.with_auto_default(
            await asyncio.to_thread(list_accounts, path)
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("account_auto_switch_config_unreadable", error=type(exc).__name__)
        return []
    decisions = await asyncio.to_thread(
        plan_switches, snapshot, accounts, switch, now=clock()
    )
    applied: List[SwitchDecision] = []
    for decision in decisions:
        try:
            status, _ = await asyncio.to_thread(
                partial(
                    set_active,
                    path,
                    decision.provider,
                    _pointer_of_decision(accounts, decision),
                    expect={
                        pointer_field(decision.provider): switch.active_for(decision.provider),
                        "auto_switch": True,
                    },
                )
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            logger.warning(
                "account_auto_switch_write_failed",
                provider=decision.provider,
                error=type(exc).__name__,
            )
            continue
        if status != config_writer.COMMITTED:
            logger.info("account_auto_switch_superseded", provider=decision.provider)
            continue
        logger.info("provider_account_auto_switched", **asdict(decision))
        record_switch(
            app_state,
            provider=decision.provider,
            from_account_id=decision.from_account_id,
            to_account_id=decision.to_account_id,
            reason="auto",
            window_kind=decision.window_kind,
            used_pct=decision.used_pct,
            window_seconds=decision.window_seconds,
        )
        applied.append(decision)
    return applied
