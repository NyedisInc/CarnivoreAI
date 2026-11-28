
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.pack.machines import exchange
from src.core.pack.rollup_import.puller import BULK_MAX_BODY, PostFn, RollupImporter

logger = structlog.get_logger()

MEMBER_PAGE_GAP_SECONDS = 0.75
MEMBER_PULL_INTERVAL_SECONDS = 30.0

_WAKE: Optional[asyncio.Event] = None
_PAIRS: List[Tuple[str, Any]] = []
_LAST: Dict[str, float] = {}
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep


def _registry_caps(iid: str) -> List[str]:
    from src.core.federation import mesh_peers
    return list(mesh_peers.REGISTRY.capabilities(iid) or []) if mesh_peers.REGISTRY is not None else []


def paced(iid: str, post: PostFn) -> PostFn:
    async def go(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
        wait = _LAST.get(iid, float("-inf")) + MEMBER_PAGE_GAP_SECONDS - _clock()
        if wait > 0:
            await _sleep(wait)
        _LAST[iid] = _clock()
        return await post(method, path, body)
    return go


def step(importer: RollupImporter, *, star_ids: Callable[[], List[str]], caps: Optional[Callable[[str], List[str]]] = None) -> Callable[[Any, Any], Awaitable[None]]:
    getcaps = caps or _registry_caps

    async def publish(service: Any, lst: Any) -> None:
        pairs = service.member_pairs(lst)
        ids: FrozenSet[str] = frozenset(iid for iid, _client in pairs)
        importer.members = ids
        importer.member_caps = {iid: list(getcaps(iid) or []) for iid in ids}
        importer.live = ids | frozenset(star_ids())
        _PAIRS[:] = pairs
        if _WAKE is not None:
            _WAKE.set()
    return publish


def on_list(importer: RollupImporter, lst: Any, self_iid: str) -> None:
    from src.core.computers import mesh_choice
    keep = frozenset(mesh_choice.eligible_ids(lst, self_iid))
    gone = frozenset(importer.members) - keep
    importer.members = frozenset(importer.members) & keep
    importer.member_caps = {iid: caps for iid, caps in importer.member_caps.items() if iid in keep}
    if importer.live is not None:
        importer.live = frozenset(importer.live) - gone
    _PAIRS[:] = [(iid, client) for iid, client in _PAIRS if iid in keep]
    _prune_tasks(keep)


def _prune_tasks(keep: FrozenSet[str]) -> None:
    for iid in [i for i, t in _TASKS.items() if t.done() or i not in keep]:
        task = _TASKS.pop(iid)
        if not task.done():
            task.cancel()


async def pull_once(importer: RollupImporter, pairs: List[Tuple[str, Any]]) -> None:
    async def one(iid: str, client: Any) -> None:
        try:
            await importer.maybe_pull_member(iid, paced(iid, exchange.bulk_post_via(client, max_body=BULK_MAX_BODY)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("member_pull_failed", peer=iid[:8], error_type=type(exc).__name__)
    await asyncio.gather(*(one(iid, client) for iid, client in pairs))


_TASKS: Dict[str, "asyncio.Task[None]"] = {}


async def _pull_member(importer: RollupImporter, iid: str, client: Any) -> None:
    try:
        await importer.maybe_pull_member(iid, paced(iid, exchange.bulk_post_via(client, max_body=BULK_MAX_BODY)))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("member_pull_failed", peer=iid[:8], error_type=type(exc).__name__)


async def run(importer: RollupImporter) -> None:
    global _WAKE
    _WAKE = asyncio.Event()
    if _PAIRS:
        _WAKE.set()
    try:
        while True:
            try:
                await asyncio.wait_for(_WAKE.wait(), timeout=MEMBER_PULL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
            _WAKE.clear()
            _prune_tasks(frozenset(i for i, _client in _PAIRS))
            for iid, client in list(_PAIRS):
                task = _TASKS.get(iid)
                if task is None or task.done():
                    _TASKS[iid] = asyncio.create_task(_pull_member(importer, iid, client), name="member-pull")
    finally:
        tasks = list(_TASKS.values())
        _TASKS.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
