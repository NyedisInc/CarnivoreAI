
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import structlog

from src.core.session_boot_readopt_plan import (
    ID_SOURCE_DERIVED,
    derived_id_for,
    resolve_session_id,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "AdoptIdentity",
    "resolve_adopt_identity",
]


@dataclass(frozen=True)
class AdoptIdentity:

    session_id: str
    id_source: str
    rekeyed: bool

    def log_if_rekeyed(self, name: str) -> None:
        if self.rekeyed:
            logger.info(
                "adopt_rekeyed_to_stored_id",
                session=name,
                session_id=self.session_id,
                id_source=self.id_source,
                note=(
                    "this session already had a row, so it is registered "
                    "under the id its agent presents on hooks rather than "
                    "a fresh adopted: id"
                ),
            )


def resolve_adopt_identity(
    *,
    name: str,
    epoch: Optional[int],
    row_lookup: Callable[[str, Optional[int]], Optional[Dict[str, Any]]],
    hook_names: Dict[str, str],
) -> AdoptIdentity:
    if epoch is None:
        return AdoptIdentity(derived_id_for(name), ID_SOURCE_DERIVED, False)

    row = row_lookup(name, epoch)
    if row is None:
        return AdoptIdentity(derived_id_for(name), ID_SOURCE_DERIVED, False)

    session_id, id_source = resolve_session_id(name, row, hook_names)
    return AdoptIdentity(
        session_id, id_source, id_source != ID_SOURCE_DERIVED
    )
