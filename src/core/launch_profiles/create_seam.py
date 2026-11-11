
from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import structlog

from src.core.agent_families import AGENT_FAMILY_BY_NAME
from src.core.launch_profiles.plan import LaunchPlan
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import materialize
from src.core.launch_record import launch_record_json
from src.core.sessions import launch_overlay

logger = structlog.get_logger()


def known_pick_ids(settings: Any) -> list:
    from src.core.session_agent_choice import configured_wrapper_ids

    return sorted({p.id for p in settings.get_launch_profiles()} | set(configured_wrapper_ids(settings) or []))


def check_explicit_pick(settings: Any, agent_type: Optional[str]) -> None:
    asked = (agent_type or "").strip().lower()
    if not asked or asked in AGENT_FAMILY_BY_NAME:
        return
    ids = known_pick_ids(settings)
    if asked not in {i.lower() for i in ids}:
        error = LaunchProfileNotFound(asked)
        error.available = ids
        raise error


def far_host_agent_type(settings: Any, agent_type: Optional[str]) -> Optional[str]:
    asked = (agent_type or "").strip().lower()
    if not asked or asked in AGENT_FAMILY_BY_NAME:
        return agent_type
    for profile in settings.get_launch_profiles():
        if profile.id.lower() == asked:
            return profile.harness
    return agent_type


def _active_account_id(harness: str) -> Optional[str]:
    from src.core.account_switch import launch_env, store
    from src.core.account_switch.active import PROVIDERS, find_account
    from src.core.provider_ledger import accounts_store, relay_accounts

    if harness not in PROVIDERS:
        return None
    path: Path = launch_env._config_path()
    try:
        pointer = store.read_switch(path).active_for(harness)
        account = find_account(relay_accounts.with_relay(accounts_store.list_accounts(path)), pointer, harness) if pointer else None
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("launch_record_account_unreadable", error=type(exc).__name__)
        return None
    return account.id if account is not None else None


def recorded_account_id(harness: str, account_id: Optional[str]) -> Optional[str]:
    from src.core.account_switch import launch_env, session_pin, shared_links
    from src.core.account_switch.active import PROVIDERS, find_account
    from src.config.provider_accounts import profile_dir_for

    if account_id is None or harness not in PROVIDERS:
        return _active_account_id(harness)
    try:
        account = find_account(session_pin.all_accounts(launch_env._config_path()), account_id, harness)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("launch_record_account_unreadable", error=type(exc).__name__)
        return account_id
    if account is None:
        return _active_account_id(harness)
    if shared_links.is_default_profile(account.provider, profile_dir_for(account)):
        return None
    return account_id


@dataclass(frozen=True)
class PreparedLaunch:

    staged: Dict[str, str]
    record: str
    late: Dict[str, str] = field(default_factory=dict)


async def record_for(plan: LaunchPlan, account_id: Optional[str] = None, overlay_note: Optional[Mapping[str, Any]] = None) -> str:
    account = await asyncio.to_thread(recorded_account_id, plan.display.harness, account_id)
    return launch_record_json(plan, account, overlay_note) if overlay_note else launch_record_json(plan, account)


async def prepare(plan: LaunchPlan, *, account_id: Optional[str] = None,
                  overlay_ctx: Optional[launch_overlay.OverlayContext] = None) -> PreparedLaunch:
    staged = await materialize(plan) if plan.secret_refs else {}
    late: Dict[str, str] = {}
    note: Optional[Mapping[str, Any]] = None
    provider = launch_overlay.get()
    if plan.overlay is not None and plan.purpose == "pane":
        if provider is None or overlay_ctx is None:
            late, note = launch_overlay.direct_secrets(plan.overlay), {"tethered": False, "reason": "argent down at launch"}
        else:
            tail = list(plan.argv_tail)
            resume = next((tail[i + 1] for i, a in enumerate(tail[:-1]) if a in ("--resume", "resume")), "")
            delivery = await provider.materialize(plan.overlay, dataclasses.replace(overlay_ctx, resume_uuid=resume) if resume else overlay_ctx)
            late, note = dict(delivery.secrets), delivery.note
    return PreparedLaunch(staged=staged, record=await record_for(plan, account_id, note), late=late)


async def scrub_staging(backend: Any, staged: Dict[str, str]) -> None:
    from src.core.tmux_backend import TmuxBackend

    if not staged or not isinstance(backend, TmuxBackend):
        return
    await backend.set_session_environment(
        f"={backend.tmux_session}", {name: None for name in staged}, note="launch_secret_scrub")


def overlay_ctx_for(plan: LaunchPlan, tmux_name: str, working_dir: str, label: Optional[str]) -> launch_overlay.OverlayContext:
    return launch_overlay.OverlayContext(harness=plan.display.harness, session_ref=tmux_name, working_dir=working_dir,
                                         display_name=(label or tmux_name))


async def deliver_late(backend: Any, prepared: PreparedLaunch) -> None:
    from src.core.tmux_backend import TmuxBackend

    if not prepared.late or not isinstance(backend, TmuxBackend):
        return
    outcome = await backend.set_session_environment(f"={backend.tmux_session}", dict(prepared.late), note="launch_overlay_deliver")
    logger.info("launch_overlay_delivered", names=sorted(prepared.late), failed=len(outcome.failures))
