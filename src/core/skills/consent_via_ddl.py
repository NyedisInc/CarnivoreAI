
from __future__ import annotations

import sqlite3
from typing import Tuple

INSTALLED_ITEMS_TABLE = "installed_items"
CONSENT_VIA_COLUMN = "consent_via"

CONSENT_SHEET = "sheet"
CONSENT_ONE_CLICK = "one_click"
CONSENT_BLUEPRINT = "blueprint"
CONSENT_PACK = "pack"
CONSENT_VIA_VALUES: Tuple[str, ...] = (CONSENT_SHEET, CONSENT_ONE_CLICK, CONSENT_BLUEPRINT, CONSENT_PACK)

OLD_CONSENT_CHECK = f"CHECK ({CONSENT_VIA_COLUMN} IN ('sheet', 'one_click', 'blueprint'))"
NEW_CONSENT_CHECK = f"CHECK ({CONSENT_VIA_COLUMN} IN ({', '.join(repr(v) for v in CONSENT_VIA_VALUES)}))"

DDL_V41_ADD_CONSENT_VIA = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {CONSENT_VIA_COLUMN} "
    f"TEXT NOT NULL DEFAULT '{CONSENT_SHEET}' "
    f"CHECK ({CONSENT_VIA_COLUMN} IN ('sheet', 'one_click', 'blueprint'))"
)

DDL_CONSENT_VIA_CURRENT = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {CONSENT_VIA_COLUMN} "
    f"TEXT NOT NULL DEFAULT '{CONSENT_SHEET}' {NEW_CONSENT_CHECK}"
)

V41_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (INSTALLED_ITEMS_TABLE, CONSENT_VIA_COLUMN, DDL_CONSENT_VIA_CURRENT),
)

REVERSAL_SQL_V41: Tuple[str, ...] = ()


def widen_consent_check(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (INSTALLED_ITEMS_TABLE,)).fetchone()
    sql = row[0] if row and row[0] else ""
    if not sql or CONSENT_VIA_COLUMN not in sql or NEW_CONSENT_CHECK in sql:
        return False
    if OLD_CONSENT_CHECK not in sql:
        raise RuntimeError(f"{INSTALLED_ITEMS_TABLE} does not carry the expected consent_via CHECK: {sql!r}")
    conn.execute("PRAGMA writable_schema=ON")
    try:
        conn.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
                     (sql.replace(OLD_CONSENT_CHECK, NEW_CONSENT_CHECK), INSTALLED_ITEMS_TABLE))
    finally:
        conn.execute("PRAGMA writable_schema=RESET")
    return True
