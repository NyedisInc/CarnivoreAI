
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.db_reuse.lent import LentConnection
from src.core.db_reuse.pooled_read import ReadPool

logger = structlog.get_logger()

_POOL = ReadPool(lambda path: connect(path, create=False))


def lend_pooled_read(path: Path) -> Optional[LentConnection]:
    """This thread's reused read connection to the datastore, or None when it does not exist or cannot be opened.

    Description: never creates the file (an absent datastore is None, as ``_writable_datastore_connection`` answered). The caller
      must not rely on closing it: ``close`` does nothing.
    Inputs: path (Path) - ``carnivore.db``. Output: LentConnection | None.
    Example: conn = lend_pooled_read(db_path_for(state_dir))
    """
    if not Path(path).exists():
        return None
    try:
        return _POOL.lend(path)
    except DatastoreUnreadableError as exc:
        logger.warning("name_read_datastore_unavailable", error=str(exc))
        return None


def lend_for_state_dir(get_state_dir: Callable[[], Path]) -> Optional[LentConnection]:
    """:func:`lend_pooled_read` for the datastore under the state directory, never raising (a decoration read must not fail its payload).

    Inputs: get_state_dir (() -> Path) - resolved at call time, so a repointed state directory is honored. Output: LentConnection | None.
    Example: conn = lend_for_state_dir(settings.get_state_dir)
    """
    try:
        return lend_pooled_read(db_path_for(get_state_dir()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("pooled_datastore_unavailable", error=str(exc))
        return None
