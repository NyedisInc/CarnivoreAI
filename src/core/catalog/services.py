
from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from src.core.catalog.index_cache import IndexCache
from src.core.catalog.trust_root import TrustRoot
from src.core.skills.ledger import InstallLedger
from src.core.skills.loadout_ledger import LoadoutLedger
from src.core.skills.plan_tokens import StagedPlanStore


@dataclass(frozen=True)
class CatalogServices:

    trust_root: TrustRoot
    index_cache: IndexCache
    staged_plans: StagedPlanStore
    open_db: Callable[[], sqlite3.Connection]
    index_url: Callable[[], str]
    api_base_url: Callable[[], str]

    @property
    def publisher_key_id(self) -> str:
        key = self.trust_root.publisher_key
        return "" if key is None else key.key_id

    @contextmanager
    def ledger(self) -> Iterator[InstallLedger]:
        with closing(self.open_db()) as conn:
            yield InstallLedger(conn)


    @contextmanager
    def loadouts(self) -> Iterator[LoadoutLedger]:
        with closing(self.open_db()) as conn:
            yield LoadoutLedger(conn)


def build_catalog_services(
    *,
    index_url: Callable[[], str],
    api_base_url: Callable[[], str],
    clock,
    open_db: Callable[[], sqlite3.Connection],
    trust_root: Optional[TrustRoot] = None,
    index_cache: Optional[IndexCache] = None,
    staged_plans: Optional[StagedPlanStore] = None,
) -> CatalogServices:
    from src.core.catalog.trust_root import production_trust_root

    resolved_root = trust_root if trust_root is not None else production_trust_root()
    resolved_cache = (
        index_cache
        if index_cache is not None
        else IndexCache(
            index_url=index_url,
            trust_root=resolved_root,
            clock=clock,
            open_db=open_db,
        )
    )
    resolved_plans = (
        staged_plans if staged_plans is not None else StagedPlanStore(clock=clock)
    )
    return CatalogServices(
        trust_root=resolved_root,
        index_cache=resolved_cache,
        staged_plans=resolved_plans,
        open_db=open_db,
        index_url=index_url,
        api_base_url=api_base_url,
    )
