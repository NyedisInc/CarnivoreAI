
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional, TypeVar

from src.core.exports.store import (  # noqa: F401
    CRATE_WRITTEN_PREFIX,
    Bundle,
    BundleNotFound,
    ExportsError,
    InvalidExport,
    Location,
    Pointer,
    bundle,
    crate_written_key,
    iso_utc,
    list_bundles,
    pointers_for,
    record_bundle,
    update_bundle,
)

T = TypeVar("T")


class MainDbUnreadable(ExportsError):

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


def with_main_db(work: Callable[[sqlite3.Connection], T], *, state: Optional[Path] = None) -> T:
    from src.core.db import DatastoreUnreadableError, connect, db_path_for
    from src.cplugs.sdk.transcript_files import state_dir

    try:
        conn = connect(db_path_for(state if state is not None else state_dir()), create=False)
    except DatastoreUnreadableError as exc:
        raise MainDbUnreadable(str(exc), missing=exc.path is not None and not Path(exc.path).exists()) from exc
    with closing(conn):
        return work(conn)


__all__ = ["Bundle", "BundleNotFound", "CRATE_WRITTEN_PREFIX", "ExportsError", "InvalidExport", "Location", "MainDbUnreadable", "Pointer", "bundle",
           "crate_written_key", "iso_utc", "list_bundles", "pointers_for", "record_bundle", "update_bundle", "with_main_db"]
