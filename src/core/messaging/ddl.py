"""Schema v73: the messaging tables (issue #1499, ``docs/messaging.md`` section 2); schema v92: ``unconfirmed`` (#1770).

Additive, five tables. Nothing here holds a secret: a provider's URL, token and owner handles, and every provider
conversation id, live in the Keychain (``src/core/messaging/secrets.py``). A conversation row keeps only an HMAC of its
provider id (``match_key``), so an inbound event can be matched without a Keychain read and without the database
holding a phone number in any recoverable form.

- ``messaging_messages.status`` gains ``unconfirmed``: an outbound text whose outcome is unknown (the bridge restarted
  mid-send, or answered "in doubt") used to be logged ``failed`` with the reason "may have been sent; do not resend: ...".
  SQLite cannot alter a CHECK, so :func:`apply_v92` REBUILDS the table (rows copied with their ids, indexes recreated) and
  turns every row carrying that reason into ``unconfirmed``. :data:`DDL_V73` is left as it was: history is not edited, and a
  fresh database runs v73 then v92 and ends with the same table.
- ``messaging_providers.replay_proven_at``: when a retry last got the provider's ``Idempotent-Replayed`` answer for a
  repeated ``Idempotency-Key`` (null: never seen). The provider card shows it.

PURE STDLIB: ``db_steps`` runs :func:`apply_v73` and :func:`apply_v92`; ``db_schema_audit`` reads :data:`DDL_V73` and
:data:`V92_COLUMNS`.
"""

from __future__ import annotations

import sqlite3
from typing import Tuple

STATUS_FAILED = "failed"
STATUS_UNCONFIRMED = "unconfirmed"

V92_MAY_HAVE_SENT_PREFIX = "may have been sent; do not resend"

DDL_V73: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS messaging_providers (
        id               TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        owner_label      TEXT NOT NULL DEFAULT 'the owner',
        enabled          INTEGER NOT NULL DEFAULT 1,
        allow_private    INTEGER NOT NULL DEFAULT 0,
        allow_plain_http INTEGER NOT NULL DEFAULT 0,
        capabilities     TEXT,
        stream_state     TEXT NOT NULL DEFAULT 'stopped',
        cursor           INTEGER NOT NULL DEFAULT 0,
        gap              TEXT,
        last_event_at    REAL,
        created_at       REAL NOT NULL,
        updated_at       REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS messaging_conversations (
        id           TEXT PRIMARY KEY,
        provider_id  TEXT NOT NULL REFERENCES messaging_providers(id) ON DELETE CASCADE,
        label        TEXT NOT NULL,
        match_key    TEXT NOT NULL,
        created_at   REAL NOT NULL,
        UNIQUE (provider_id, match_key)
    )""",
    """CREATE TABLE IF NOT EXISTS messaging_bindings (
        id              TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES messaging_conversations(id) ON DELETE CASCADE,
        session_uuid    TEXT NOT NULL,
        direction       TEXT NOT NULL CHECK (direction IN ('in','out','both')),
        is_default      INTEGER NOT NULL DEFAULT 0,
        held_notice     INTEGER NOT NULL DEFAULT 1,
        created_at      REAL NOT NULL,
        created_by      TEXT NOT NULL,
        UNIQUE (conversation_id, session_uuid)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_messaging_binding_default ON messaging_bindings(conversation_id) WHERE is_default = 1",
    "CREATE INDEX IF NOT EXISTS ix_messaging_binding_session ON messaging_bindings(session_uuid)",
    """CREATE TABLE IF NOT EXISTS messaging_messages (
        id                  TEXT PRIMARY KEY,
        provider_id         TEXT NOT NULL,
        conversation_id     TEXT NOT NULL DEFAULT '',
        binding_id          TEXT NOT NULL DEFAULT '',
        session_uuid        TEXT,
        direction           TEXT NOT NULL CHECK (direction IN ('in','out')),
        kind                TEXT NOT NULL CHECK (kind IN ('message','note','notice')),
        provider_message_id TEXT NOT NULL DEFAULT '',
        event_id            INTEGER,
        in_reply_to         TEXT,
        sent_at             REAL,
        received_at         REAL NOT NULL,
        text                TEXT NOT NULL,
        status              TEXT NOT NULL CHECK (status IN ('queued','held','delivering','delivered','failed')),
        reason              TEXT,
        delivered_at        REAL,
        batch_id            TEXT,
        edited_at           REAL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_messaging_inbound_once ON messaging_messages"
    "(provider_id, provider_message_id, binding_id, kind) WHERE direction = 'in'",
    "CREATE INDEX IF NOT EXISTS ix_messaging_pending ON messaging_messages(session_uuid, status)",
    "CREATE INDEX IF NOT EXISTS ix_messaging_out_reply ON messaging_messages(provider_id, provider_message_id) WHERE direction = 'out'",
    "CREATE INDEX IF NOT EXISTS ix_messaging_time ON messaging_messages(conversation_id, received_at)",
    """CREATE TABLE IF NOT EXISTS messaging_notices (
        conversation_id TEXT NOT NULL,
        notice          TEXT NOT NULL,
        episode         TEXT NOT NULL,
        sent_at         REAL NOT NULL,
        PRIMARY KEY (conversation_id, notice, episode)
    )""",
)


def apply_v73(conn: sqlite3.Connection) -> None:
    for statement in DDL_V73:
        conn.execute(statement)



V92_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("messaging_providers", "replay_proven_at",
     "ALTER TABLE messaging_providers ADD COLUMN replay_proven_at REAL"),
)

_MESSAGES = "messaging_messages"
_MESSAGES_V92 = "messaging_messages_v92"

_MESSAGES_TABLE_V92 = """CREATE TABLE {name} (
        id                  TEXT PRIMARY KEY,
        provider_id         TEXT NOT NULL,
        conversation_id     TEXT NOT NULL DEFAULT '',
        binding_id          TEXT NOT NULL DEFAULT '',
        session_uuid        TEXT,
        direction           TEXT NOT NULL CHECK (direction IN ('in','out')),
        kind                TEXT NOT NULL CHECK (kind IN ('message','note','notice')),
        provider_message_id TEXT NOT NULL DEFAULT '',
        event_id            INTEGER,
        in_reply_to         TEXT,
        sent_at             REAL,
        received_at         REAL NOT NULL,
        text                TEXT NOT NULL,
        status              TEXT NOT NULL CHECK (status IN ('queued','held','delivering','delivered','failed','unconfirmed')),
        reason              TEXT,
        delivered_at        REAL,
        batch_id            TEXT,
        edited_at           REAL
    )"""

_MESSAGES_INDEXES_V92: Tuple[str, ...] = tuple(s for s in DDL_V73 if " ON messaging_messages" in s)


def apply_v92(conn: sqlite3.Connection) -> None:
    if "replay_proven_at" not in {r[1] for r in conn.execute("PRAGMA table_info(messaging_providers)")}:
        conn.execute(V92_COLUMNS[0][2])
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (_MESSAGES,)).fetchone()
    if row is None or STATUS_UNCONFIRMED in row[0]:
        return
    conn.execute(f"DROP TABLE IF EXISTS {_MESSAGES_V92}")
    conn.execute(_MESSAGES_TABLE_V92.format(name=_MESSAGES_V92))
    new_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_MESSAGES_V92})")]
    old_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_MESSAGES})")}
    kept = [c for c in new_cols if c in old_cols]
    pick = ", ".join(
        f"CASE WHEN status = '{STATUS_FAILED}' AND reason LIKE '{V92_MAY_HAVE_SENT_PREFIX}%' "
        f"THEN '{STATUS_UNCONFIRMED}' ELSE status END" if c == "status" else c for c in kept)
    conn.execute(f"INSERT INTO {_MESSAGES_V92} ({', '.join(kept)}) SELECT {pick} FROM {_MESSAGES}")
    conn.execute(f"DROP TABLE {_MESSAGES}")
    conn.execute(f"ALTER TABLE {_MESSAGES_V92} RENAME TO {_MESSAGES}")
    for statement in _MESSAGES_INDEXES_V92:
        conn.execute(statement)
