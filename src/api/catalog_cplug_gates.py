
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import structlog

from src.api.catalog_install_support import refuse_409
from src.core.catalog.first_party_listing import pinned_key_id
from src.cplugs.host import identity, install_gates, runtime
from src.cplugs.host import state as owner_state
from src.cplugs.host.install_gates import CplugFacts, CplugGateRefusal
from src.cplugs.host.secret_store import SecretError, SecretStore
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.host.state import StateWriteFailed

logger = structlog.get_logger(__name__)

CPLUGS_TOPIC = "cplugs"


def _item_name(item_id: str) -> str:
    return item_id.partition("/")[2]


def _shipped_ids() -> frozenset:
    return frozenset(d.id for d in runtime.definitions())


async def gate_staged_cplug(request: Any, item: Any, staged_path: Path, version: Any = None) -> CplugFacts:
    state_dir = request.app.state.services.settings_reader.state_dir()

    def work() -> CplugFacts:
        name = _item_name(item.id)
        facts = install_gates.evaluate(item.id, staged_path, getattr(getattr(version, "sig", None), "key_id", "") or "", pinned_key_id() or "")
        problem = install_gates.name_problem(state_dir, name, item.id, _shipped_ids())
        if problem is not None:
            raise problem
        return facts

    try:
        return await asyncio.to_thread(work)
    except CplugGateRefusal as exc:
        raise refuse_409(exc.code, exc.detail)
    except identity.LedgerUnreadable:
        raise refuse_409("cplug_ledger_unreadable", "the plugin install ledger cannot be read; nothing was installed")


def check_cplug_consent(consent: Any, facts: CplugFacts) -> None:
    try:
        install_gates.check_consent(consent, facts)
    except CplugGateRefusal as exc:
        raise refuse_409(exc.code, exc.detail)


def reserve_install(request: Any, item: Any) -> bool:
    state_dir = request.app.state.services.settings_reader.state_dir()
    name = _item_name(item.id)
    try:
        existed = identity.lookup(state_dir, name) is not None
        identity.register_install(state_dir, name, item.id, _shipped_ids())
    except identity.InstallRefused as exc:
        raise refuse_409(exc.code, str(exc))
    except identity.LedgerUnreadable:
        raise refuse_409("cplug_ledger_unreadable", "the plugin install ledger cannot be read; nothing was installed")
    except (StateWriteFailed, OSError) as exc:
        logger.error("cplug_install_reserve_failed", item_id=item.id, error_type=type(exc).__name__)
        raise refuse_409("cplug_ledger_unwritable", "the plugin install ledger could not be written; nothing was installed")
    return not existed


def release_reservation(request: Any, item: Any) -> None:
    state_dir = request.app.state.services.settings_reader.state_dir()
    try:
        identity.release_install(state_dir, _item_name(item.id))
    except (identity.LedgerUnreadable, StateWriteFailed, OSError) as exc:
        logger.warning("cplug_install_release_failed", item_id=item.id, error_type=type(exc).__name__)


def release_if_empty(request: Any, row: Any) -> bool:
    state_dir = request.app.state.services.settings_reader.state_dir()
    name = _item_name(row.item_id)
    try:
        record = identity.lookup(state_dir, name)
        if record is None:
            return False
        folder = identity.data_dir(state_dir, record.uuid)
        if (folder.is_dir() and any(f.is_file() for f in folder.rglob("*"))) or name in owner_state.stored_ids(state_dir):
            return False
        if SecretStore(state_dir).holds(identity.data_key(record)):
            return False
        return identity.release_install(state_dir, name)
    except (identity.LedgerUnreadable, SecretError, StateWriteFailed, OSError) as exc:
        logger.warning("cplug_uninstall_release_failed", item_id=row.item_id, error_type=type(exc).__name__)
        return False


def reload_and_push(request: Any) -> None:
    live = getattr(request.app.state, "sidecar_runtime", None)
    if live is not None:
        live.load_registry()
    from src.core import resource_push  # noqa: PLC0415

    resource_push.notify(CPLUGS_TOPIC)


async def stop_before_uninstall(request: Any, row: Any) -> None:
    live = getattr(request.app.state, "sidecar_runtime", None)
    if live is None:
        return
    name = _item_name(row.item_id)
    await live.supervisor.disable(name, "uninstalled")
    await asyncio.to_thread(live.effects.cancel, name)
    live.supervisor.forget(name)


async def stop_before_update(request: Any, row: Any) -> None:
    live = getattr(request.app.state, "sidecar_runtime", None)
    if live is None:
        return
    name = _item_name(row.item_id)
    await live.supervisor.disable(name, "updated")
    await asyncio.to_thread(live.effects.cancel, name)


async def resume_after_failed_update(request: Any, row: Any) -> None:
    live = getattr(request.app.state, "sidecar_runtime", None)
    d = runtime.find(_item_name(row.item_id))
    if live is None or not isinstance(d, SidecarDefinition):
        return
    host = runtime.host_for(request.app)
    try:
        if await asyncio.to_thread(host.enabled, d.id):
            await host.restart_sidecar(d)
            await live.mcp_health_switched(d.id, True)
        host.publish(CPLUGS_TOPIC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cplug_resume_after_failed_update_failed", cplug=d.id, error_type=type(exc).__name__)


def strip_grant_after_update(request: Any, row: Any) -> bool:
    reload_and_push(request)
    state_dir = request.app.state.services.settings_reader.state_dir()
    d = runtime.find(_item_name(row.item_id))
    if not isinstance(d, SidecarDefinition):
        return False
    st = owner_state.get(state_dir, d.manifest)
    if st.digest == d.manifest.code_digest and set(d.manifest.permissions) <= set(st.grants):
        return False
    owner_state.update(state_dir, d.manifest, None, lambda cur: replace(cur, grants=(), digest=""))
    from src.core import resource_push  # noqa: PLC0415

    resource_push.notify(CPLUGS_TOPIC)
    return True
