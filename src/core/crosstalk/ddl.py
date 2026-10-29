
from __future__ import annotations

import sqlite3

DDL_V57 = (
    """CREATE TABLE IF NOT EXISTS crosstalk_messages (
        id TEXT PRIMARY KEY,
        native_key TEXT UNIQUE,
        source TEXT NOT NULL DEFAULT 'crosstalk',
        thread TEXT NOT NULL,
        sender_key TEXT NOT NULL,
        receiver_key TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        sender_uuid TEXT,
        receiver_uuid TEXT,
        sender_epoch INTEGER,
        receiver_epoch INTEGER,
        sender_name TEXT NOT NULL,
        sender_provider TEXT NOT NULL,
        sender_model TEXT,
        receiver_name TEXT,
        receiver_provider TEXT,
        receiver_model TEXT,
        text TEXT NOT NULL,
        in_reply_to TEXT,
        expect_reply INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ('queued','held','delivering','delivered','failed','expired')),
        reason TEXT,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        delivered_at REAL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_receiver_queue ON crosstalk_messages(receiver_key,status,created_at)",
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_thread ON crosstalk_messages(thread,created_at)",
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_sender_time ON crosstalk_messages(sender_key,created_at)",
    """CREATE TABLE IF NOT EXISTS crosstalk_contacts (
        pair_key TEXT PRIMARY KEY,
        left_key TEXT NOT NULL,
        right_key TEXT NOT NULL,
        left_epoch INTEGER,
        right_epoch INTEGER,
        granted_at REAL NOT NULL,
        source TEXT NOT NULL,
        last_owner_input REAL NOT NULL DEFAULT 0,
        paused INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS crosstalk_watches (
        id TEXT PRIMARY KEY,
        watcher_key TEXT NOT NULL,
        watcher_id TEXT NOT NULL,
        watcher_epoch INTEGER,
        target_key TEXT NOT NULL,
        target_id TEXT NOT NULL,
        target_epoch INTEGER,
        once INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('watching','notified','expired')),
        notifications INTEGER NOT NULL DEFAULT 0,
        notified_at REAL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_watch_target ON crosstalk_watches(target_key,status)",
)


V94_COLUMNS = (
    ("crosstalk_messages", "task_item", "ALTER TABLE crosstalk_messages ADD COLUMN task_item INTEGER"),
)
V94_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_task_item ON crosstalk_messages(task_item,created_at)",
)


DDL_V102 = (
    "CREATE INDEX IF NOT EXISTS ix_crosstalk_in_reply_to ON crosstalk_messages(in_reply_to,sender_key) WHERE in_reply_to IS NOT NULL",
)


def apply_v94(conn: sqlite3.Connection) -> None:
    for table, column, statement in V94_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    if {row[1] for row in conn.execute("PRAGMA table_info(crosstalk_messages)")}:
        for statement in V94_INDEXES:
            conn.execute(statement)


def apply_v57(conn: sqlite3.Connection) -> None:
    for statement in DDL_V57:
        conn.execute(statement)


def apply_v102(conn: sqlite3.Connection) -> None:
    for statement in DDL_V102:
        conn.execute(statement)
