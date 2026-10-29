
from __future__ import annotations

from functools import lru_cache

from src.core.inventory import registry_main, registry_side
from src.core.inventory.claims import ClaimBook


@lru_cache(maxsize=1)
def book() -> ClaimBook:
    return ClaimBook(
        [*registry_main.claims(), *registry_side.claims()],
        [*registry_main.exclusions(), *registry_side.exclusions()],
        registry_side.excluded_stores(),
    )
