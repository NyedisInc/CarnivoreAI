
from __future__ import annotations

import sqlite3
from typing import Sequence

from src.core.pipeline import contract as C
from src.core.stats import rollup as pack_rollup
from src.core.stats.plugin import carry, ingest, schema

PLUGIN_ID = "stats"
DB_NAME = "stats.db"


def on_events(conn: sqlite3.Connection, events: Sequence[C.Event]) -> None:
    for event in events:
        ingest.on_event(conn, event)


STATS = C.Plugin(id=PLUGIN_ID, db_name=DB_NAME, schema_version=schema.SCHEMA_VERSION, migrate=schema.migrate,
                 on_events=on_events, carry_over=carry.carry_over, export_rollup=pack_rollup.export_rollup)
