
from __future__ import annotations

from typing import Tuple

FEDERATION_GRANTS_TABLE = "federation_grants"

DDL_FEDERATION_GRANTS = """
CREATE TABLE IF NOT EXISTS federation_grants (
  grant_id        TEXT PRIMARY KEY,
  peer_install_id TEXT NOT NULL,
  public_key      TEXT NOT NULL,
  fid             TEXT NOT NULL,
  label           TEXT NOT NULL DEFAULT '',
  scopes          TEXT NOT NULL DEFAULT 'sessions',
  remote_grant_id TEXT,
  created_at      TEXT NOT NULL,
  last_seen_at    TEXT,
  revoked_at      TEXT
)
"""

DDL_FEDERATION_GRANTS_LIVE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_federation_grants_live_peer
  ON federation_grants(peer_install_id) WHERE revoked_at IS NULL
"""

DDL_V43: Tuple[str, ...] = (DDL_FEDERATION_GRANTS, DDL_FEDERATION_GRANTS_LIVE_INDEX)

REVERSAL_SQL_V43: Tuple[str, ...] = (
    "DROP INDEX IF EXISTS ux_federation_grants_live_peer",
    "DROP TABLE IF EXISTS federation_grants",
)



HOSTS_TABLE = "hosts"
HOST_KIND_LOCAL, HOST_KIND_SSH, HOST_KIND_PEER = "local", "ssh", "peer"

V44_COLUMN_STATEMENTS: Tuple[Tuple[str, str], ...] = (
    ("kind", "ALTER TABLE hosts ADD COLUMN kind TEXT NOT NULL DEFAULT 'ssh'"),
    ("peer_install_id", "ALTER TABLE hosts ADD COLUMN peer_install_id TEXT"),
    ("peer_grant_id", "ALTER TABLE hosts ADD COLUMN peer_grant_id TEXT"),
    ("peer_fid", "ALTER TABLE hosts ADD COLUMN peer_fid TEXT"),
    ("peer_protocol", "ALTER TABLE hosts ADD COLUMN peer_protocol INTEGER"),
    ("peer_state", "ALTER TABLE hosts ADD COLUMN peer_state TEXT"),
    ("peer_initiator", "ALTER TABLE hosts ADD COLUMN peer_initiator INTEGER"),
    ("peer_port", "ALTER TABLE hosts ADD COLUMN peer_port INTEGER"),
    ("peer_back_kind", "ALTER TABLE hosts ADD COLUMN peer_back_kind TEXT"),
)

V44_COLUMNS: Tuple[Tuple[str, str, str], ...] = tuple((HOSTS_TABLE, c, s) for c, s in V44_COLUMN_STATEMENTS)

REVERSAL_SQL_V44: Tuple[str, ...] = ()


def apply_v44(conn) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({HOSTS_TABLE})")}
    if not present:
        return
    for column, statement in V44_COLUMN_STATEMENTS:
        if column not in present:
            conn.execute(statement)
    conn.execute("UPDATE hosts SET kind = 'local' WHERE key = 'local'")
