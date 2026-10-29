
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.session_boot_readopt_plan import (
    ADOPTED_ID_PREFIX,
    CLAIMABLE_ORIGINS,
    ID_SOURCE_DERIVED,
    ID_SOURCE_HOOK_TOKEN,
    ID_SOURCE_LEGACY_ROW,
    READOPT_CANNOT_DETERMINE,
    READOPT_RAN,
    SKIP_ALREADY_HELD,
    SKIP_NO_EPOCH,
    SKIP_NO_ROW,
    SKIP_NOT_CLAIMABLE_ORIGIN,
    ReadoptPlan,
    ReadoptReport,
    ReadoptTarget,
    derived_id_for,
    plan_readopt,
    resolve_session_id,
    session_for,
)

logger = structlog.get_logger()

__all__ = [
    "ADOPTED_ID_PREFIX",
    "CLAIMABLE_ORIGINS",
    "ID_SOURCE_DERIVED",
    "ID_SOURCE_HOOK_TOKEN",
    "ID_SOURCE_LEGACY_ROW",
    "READOPT_CANNOT_DETERMINE",
    "READOPT_RAN",
    "SKIP_ALREADY_HELD",
    "SKIP_NO_EPOCH",
    "SKIP_NO_ROW",
    "SKIP_NOT_CLAIMABLE_ORIGIN",
    "ReadoptPlan",
    "ReadoptReport",
    "ReadoptTarget",
    "derived_id_for",
    "plan_readopt",
    "readopt_surviving_sessions",
    "resolve_session_id",
    "schedule_boot_readopt",
    "session_for",
]


def _hook_names(manager: Any) -> Dict[str, str]:
    authority = getattr(manager, "hook_tokens", None)
    return dict(getattr(authority, "tmux_names", None) or {})


def _record_epoch_for_already_registered(
    manager: Any, plan: "ReadoptPlan", listing: Any
) -> None:
    already_held = plan.skipped_for(SKIP_ALREADY_HELD)
    if not already_held:
        return

    epoch_by_name: Dict[str, int] = {}
    for row in listing.sessions:
        name = row.get("name")
        raw_epoch = row.get("created_at_epoch")
        if not name or raw_epoch is None:
            continue
        try:
            epoch_by_name[name] = int(raw_epoch)
        except (TypeError, ValueError):
            continue

    name_to_session_id = {
        getattr(backend, "tmux_session", None): sid
        for sid, backend in manager._registry.backends.items()
    }

    for name in already_held:
        session_id = name_to_session_id.get(name)
        if session_id is None:
            continue
        if manager._instance_epochs.get(session_id) is not None:
            continue
        epoch = epoch_by_name.get(name)
        if epoch is None:
            continue
        manager._instance_epochs[session_id] = epoch
        logger.info(
            "boot_readopt_epoch_recorded_for_registered",
            session_id=session_id,
            tmux_name=name,
            epoch=epoch,
        )


def probe_instances(manager: Any) -> Any:
    from src.config import settings
    from src.core.session_backend import build_backend
    from src.core.tmux_listing import coerce_listing
    from src.core.tmux_socket_resolution import (
        configured_tmux_socket_name,
        resolve_probe_socket,
    )

    def _list_for_socket(socket_name: str):
        probe = build_backend(
            settings,
            session_id="__readopt_probe__",
            working_dir=Path.home(),
            on_output=None,
            socket_name_override=socket_name,
        )
        actual_socket = getattr(probe, "socket_name", None) or socket_name
        return actual_socket, coerce_listing(probe.list_attachable_sessions())

    configured = configured_tmux_socket_name(settings)
    return resolve_probe_socket(manager, configured, _list_for_socket)


def schedule_boot_readopt(
    manager: Any, listing: Any = None
) -> Optional["asyncio.Task"]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("boot_readopt_not_scheduled", reason="no_running_loop")
        return None

    task = loop.create_task(readopt_surviving_sessions(manager, listing))
    manager._boot_readopt_task = task
    return task


async def readopt_surviving_sessions(
    manager: Any, listing: Any = None
) -> ReadoptReport:
    from src.config import settings
    from src.core.session_backend import build_backend
    from src.core.session_store import get_instance, sessions_table_ready

    if listing is None:
        socket, listing = await asyncio.to_thread(probe_instances, manager)
    else:
        socket = manager.tmux_socket_name()
    if not listing.ok:
        logger.warning(
            "boot_readopt_listing_unavailable",
            reason=getattr(listing, "reason", None),
            note=(
                "tmux could not be enumerated, so nothing is held and "
                "nothing is disowned - not zero sessions, no answer"
            ),
        )
        return ReadoptReport(
            outcome=READOPT_CANNOT_DETERMINE,
            detail=f"listing unavailable ({getattr(listing, 'reason', None)})",
        )

    conn = None
    try:
        conn = manager._datastore_connection()
        if conn is None or not sessions_table_ready(conn):
            logger.warning(
                "boot_readopt_cannot_determine",
                live_count=len(listing.names),
                note=(
                    "the sessions table could not be read, so no live "
                    "session could be shown to be ours - holding none "
                    "rather than claiming or disowning any"
                ),
            )
            return ReadoptReport(
                outcome=READOPT_CANNOT_DETERMINE,
                detail="sessions table unavailable",
            )

        plan = plan_readopt(
            listing_rows=listing.sessions,
            row_lookup=lambda name, epoch: get_instance(
                conn, socket=socket, name=name, epoch=epoch
            ),
            hook_names=dict(_hook_names(manager)),
            held_ids=[sid for sid in manager._registry.sessions if sid in manager._registry.backends],
            held_names=[
                getattr(backend, "tmux_session", None)
                for backend in manager._registry.backends.values()
            ],
            default_working_dir=str(settings.get_working_dir()),
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    _record_epoch_for_already_registered(manager, plan, listing)

    if not plan.targets:
        logger.info(
            "boot_readopt_nothing_to_hold",
            live_count=len(listing.names),
            skipped=len(plan.skipped),
        )
        return ReadoptReport(outcome=READOPT_RAN, plan=plan)

    async def _attach(target: ReadoptTarget) -> None:
        backend = build_backend(
            settings,
            session_id=target.session_id,
            working_dir=Path(target.working_dir),
            on_output=manager._make_output_handler(target.session_id),
            viewer_probe=manager._make_viewer_probe(target.session_id),
            session_name=target.name,
            socket_name_override=socket,
        )
        await backend.attach_existing(needs_pipe_setup=True)

        session = session_for(target)
        session.pinned_theme = manager._theme_store.resolve_project_theme(
            Path(target.working_dir), target.name
        )
        manager._registry.register(session, backend)
        manager._instance_epochs[target.session_id] = target.epoch
        manager.hook_tokens.bind_name(target.session_id, target.name)

        try:
            await backend.set_session_environment(
                target.name, manager.get_env_for_spawn(target.session_id),
                note="boot_readopt_set_environment",
            )
        except (OSError, AttributeError) as exc:
            logger.debug(
                "boot_readopt_set_environment_failed",
                session=target.name,
                error=str(exc),
            )

    prior_current = manager._registry.last_session_id

    results = await asyncio.gather(
        *(_attach(target) for target in plan.targets),
        return_exceptions=True,
    )

    held: List[str] = []
    failed: List[Tuple[str, str]] = []
    for target, result in zip(plan.targets, results):
        if isinstance(result, BaseException):
            failed.append((target.name, str(result)))
            logger.warning(
                "boot_readopt_attach_failed",
                tmux_name=target.name,
                session_id=target.session_id,
                error=str(result),
            )
            continue
        held.append(target.session_id)

    if manager._registry.last_session_id in set(held):
        if prior_current is not None and prior_current in manager._registry.sessions:
            manager._registry.last_session_id = prior_current
        elif held:
            visible = [sid for sid in held if not manager._registry.is_hidden(sid)]
            if visible:
                manager._registry.last_session_id = visible[0]

    logger.info(
        "boot_readopt_complete",
        held=len(held),
        failed=len(failed),
        skipped=len(plan.skipped),
        live_count=len(listing.names),
        id_sources={
            source: sum(
                1
                for t in plan.targets
                if t.id_source == source and t.session_id in held
            )
            for source in (
                ID_SOURCE_HOOK_TOKEN,
                ID_SOURCE_LEGACY_ROW,
                ID_SOURCE_DERIVED,
            )
        },
        no_row=len(plan.skipped_for(SKIP_NO_ROW)),
    )
    from src.core.session_agent_infer_sweep import sweep_live_sessions

    await asyncio.to_thread(sweep_live_sessions, manager)

    from src.core.session_status_seed_read import seed_live_sessions

    await asyncio.to_thread(seed_live_sessions, manager)

    return ReadoptReport(
        outcome=READOPT_RAN, held=held, failed=failed, plan=plan
    )
