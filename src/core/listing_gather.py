
from __future__ import annotations

import time
from dataclasses import dataclass, field
from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Dict, Mapping, Optional, Sequence, Tuple

import structlog

from src.core.listing_prefetch import ListingPrefetch, build_listing_prefetch
from src.core.session_token_usage.listing_model_facts import (
    ModelListingFacts,
    build_model_listing_prefetch,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class ListingSnapshot:

    socket: str
    seed_candidate_names: Tuple[str, ...] = ()
    decorated_names: Tuple[str, ...] = ()
    remote_targets: Tuple[Any, ...] = ()


@dataclass(frozen=True)
class ListingReaders:

    build_status_map: Callable[[], Any]
    build_instance_index: Callable[..., Any]
    label_for_name: Callable[[Optional[str]], Optional[str]]
    identity_for_live_name: Callable[[Optional[str]], Optional[dict]]
    gather_remote: Optional[Callable[[Tuple[Any, ...]], Any]] = None
    label_identity_for_names: Optional[Callable[[Sequence[str]], Mapping[str, Tuple[Any, Any]]]] = None
    shared_connection: Optional[Callable[[], ContextManager[Any]]] = None


@dataclass(frozen=True)
class ListingGather:

    status_map: Any
    instance_index: Any
    prefetch: ListingPrefetch
    model_facts: Dict[str, ModelListingFacts] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    remote: Any = None


def gather_listing_inputs(
    readers: ListingReaders, snapshot: ListingSnapshot
) -> ListingGather:
    started = time.perf_counter()
    status_map = readers.build_status_map()
    with (readers.shared_connection or nullcontext)():
        instance_index = readers.build_instance_index(
            socket=snapshot.socket, names=list(snapshot.seed_candidate_names)
        )
        prefetch = build_listing_prefetch(
            names=snapshot.decorated_names,
            label_for_name=readers.label_for_name,
            identity_for_live_name=readers.identity_for_live_name,
            label_identity_for_names=readers.label_identity_for_names,
        )
    model_facts = build_model_listing_prefetch(
        names=snapshot.decorated_names,
        status_map=status_map,
        instance_index=instance_index,
        prefetch=prefetch,
    )
    remote = (readers.gather_remote(snapshot.remote_targets)
              if snapshot.remote_targets and readers.gather_remote is not None else None)
    return ListingGather(
        status_map=status_map,
        instance_index=instance_index,
        prefetch=prefetch,
        model_facts=model_facts,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        remote=remote,
    )


def log_gather(gather: ListingGather, names: Sequence[str]) -> None:
    logger.debug(
        "listing_gather_complete",
        elapsed_ms=round(gather.elapsed_ms, 2),
        names=len(names),
        status_map_complete=bool(getattr(gather.status_map, "complete", False)),
        prefetched=len(gather.prefetch.by_name),
    )
