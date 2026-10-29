
from __future__ import annotations

import sqlite3
from typing import Tuple

DDL_COMPUTER_LINKS: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS computer_links (
        peer_install_id  TEXT PRIMARY KEY,
        role             TEXT NOT NULL CHECK (role IN ('main', 'member', 'peer')),
        transport        TEXT NOT NULL CHECK (transport IN ('tls', 'ssh')),
        join_kind        TEXT CHECK (join_kind IN ('new', 'migrate')),
        prev_initiator   INTEGER,
        cert_der         BLOB,
        cert_sha256      TEXT,
        link_fid         TEXT,
        next_cert_der    BLOB,
        next_cert_sha256 TEXT,
        addresses        TEXT NOT NULL DEFAULT '[]',
        link_port        INTEGER,
        inbound_control  INTEGER NOT NULL DEFAULT 1,
        joined_at        TEXT,
        first_link_at    TEXT,
        last_link_at     TEXT,
        updated_at       TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_computer_links_cert ON computer_links(cert_sha256) WHERE cert_sha256 IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_computer_links_fid ON computer_links(link_fid) WHERE link_fid IS NOT NULL",
)


def apply_computer_links(conn: sqlite3.Connection) -> None:
    for statement in DDL_COMPUTER_LINKS:
        conn.execute(statement)
