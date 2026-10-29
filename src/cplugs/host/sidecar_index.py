"""The adapter between the verified catalog index and the sidecar supervisor (slice A10b, epic #2063).

``Supervisor.set_index`` takes a small mapping: ``revoked`` (entries ``{id, version}`` for one release or ``{id}`` for every
release) and ``expires_at``. The catalog side holds something else: ``IndexCache.revoked_sets`` (revoked publisher key ids and
revoked ``<item_id>@<version>`` subjects, sticky ones included) and each installed row's ``publisher_key_id``. This module
maps the one onto the other, so a revoked release or a revoked publisher key stops a RUNNING plugin within one index
refresh (``docs/cplug-platform.md`` 10.7), and an index past its deadline plus grace pauses it.

THE DEADLINE. The signed index does not carry an ``expires_at`` yet; until it does the deadline is DERIVED as ``generated_at``
plus 14 days and the mapping says so (``expires_at_derived``). With no verified index at all the mapping is ``None`` and the
supervisor fails closed (``index_state`` is ``missing``).

WHEN IT RUNS. :meth:`IndexAdapter.sync` runs from the refresher after every pass (``IndexRefresher.after_pass``), which is
also what re-judges a running plugin as time passes; :meth:`IndexAdapter.ensure` runs before every enable, so the first spawn
after boot never sees a missing index; :meth:`IndexAdapter.third_party_enabled` is what asks the refresher for an hourly pass.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional

import structlog

from src.core.catalog.revocation import VERSION_SUBJECT_SEPARATOR
from src.core.skills import kinds
from src.cplugs.host import owner_switch, sidecar_registry
from src.cplugs.host import state as owner_state

logger = structlog.get_logger()

DERIVED_LIFETIME = timedelta(days=14)
ENSURE_TIMEOUT_SECONDS = 15.0


def revoked_entries(keys: FrozenSet[str], versions: Iterable[str], rows: Iterable[Any]) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    for subject in sorted(versions):
        item_id, sep, version = subject.rpartition(VERSION_SUBJECT_SEPARATOR)
        if sep and item_id and version:
            found.append({"id": item_id, "version": version})
    for row in rows:
        if row.kind == kinds.KIND_CPLUG and str(row.publisher_key_id).strip().upper() in keys:
            found.append({"id": row.item_id})
    return found


def index_view(verified: Any, keys: FrozenSet[str], versions: Iterable[str], rows: Iterable[Any]) -> Optional[Dict[str, Any]]:
    if verified is None:
        return None
    signed = getattr(verified, "expires_at", None)
    expires = signed if signed is not None else verified.generated_at + DERIVED_LIFETIME
    return {"revoked": revoked_entries(keys, versions, rows), "expires_at": expires.isoformat(), "expires_at_derived": signed is None}


class IndexAdapter:

    def __init__(self, runtime: Any, cache: Any) -> None:
        self._runtime = runtime
        self._cache = cache

    def _index_cache(self) -> Any:
        return self._cache() if callable(self._cache) else self._cache

    def _build(self, snapshot: Any) -> Optional[Dict[str, Any]]:
        cache = self._index_cache()
        verified = snapshot.verified
        if cache is None or verified is None:
            return None
        keys, versions = cache.revoked_sets(verified)
        return index_view(verified, keys, versions, self._runtime._ledger_rows())

    async def sync(self, snapshot: Any = None) -> None:
        cache = self._index_cache()
        if cache is None:
            return
        try:
            view = await asyncio.to_thread(self._build, snapshot if snapshot is not None else cache.snapshot())
            await self._runtime.supervisor.set_index(view)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_index_sync_failed", error_type=type(exc).__name__)

    async def ensure(self) -> None:
        cache = self._index_cache()
        if cache is None:
            return
        try:
            snapshot = await asyncio.wait_for(cache.get(), ENSURE_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, OSError) as exc:
            logger.warning("cplug_index_ensure_failed", error_type=type(exc).__name__)
            snapshot = cache.snapshot()
        await self.sync(snapshot)

    def third_party_enabled(self) -> bool:
        state_dir = self._runtime.state_dir
        if not owner_switch.read(state_dir):
            return False
        registry = sidecar_registry.current()
        if registry is None:
            return False
        return any(d.manifest.tier == "catalog" and owner_state.get(state_dir, d.manifest).enabled for d in registry.listed())
