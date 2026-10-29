
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.core.companion_shell.rows import exclude_clause
from src.core.db import table_exists, transaction
from src.core.hosts import roster_push
from src.core.hosts.ddl import HOSTS_TABLE, LOCAL_HOST_KEY
from src.core.product_identity import LEGACY_TMUX_SOCKET_NAMES, TMUX_SOCKET_NAME
from src.core.trail_entry import utc_now

DEFAULT_REMOTE_SOCKET = "carnivore-remote"

RESERVED_SOCKETS = frozenset({TMUX_SOCKET_NAME, *LEGACY_TMUX_SOCKET_NAMES})

KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_TARGET_PART = r"[A-Za-z0-9_][A-Za-z0-9._+-]*"
SSH_TARGET_RE = re.compile(rf"(?:{_TARGET_PART}@)?{_TARGET_PART}")
SSH_TARGET_MAX = 254
SOCKET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
LABEL_MAX = 64
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class HostError(Exception):
    pass


class HostsUnavailable(HostError):
    pass


class HostNotFound(HostError):
    pass


class HostKeyTaken(HostError):
    pass


class HostLocalFixed(HostError):
    pass


class HostInUse(HostError):
    pass


class HostInvalid(HostError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Host:

    key: str
    label: str
    ssh_target: Optional[str]
    ssh_port: Optional[int]
    socket: Optional[str]
    enabled: bool
    tmux_path: Optional[str]
    tmux_version: Optional[str]
    login_path: Optional[str]
    agent_paths: Optional[Dict[str, str]]
    login_shell: Optional[str]
    machine_id: Optional[str]
    remote_carnivore: Optional[str]
    probe_state: str
    probe_detail: Optional[str]
    probed_at: Optional[str]
    created_at: str
    updated_at: str
    kind: str = "ssh"
    computer_install_id: Optional[str] = None

    @property
    def is_local(self) -> bool:
        return self.key == LOCAL_HOST_KEY


_COLUMNS = (
    "key, label, ssh_target, ssh_port, socket, enabled, tmux_path, tmux_version, "
    "login_path, agent_paths_json, login_shell, machine_id, remote_carnivore, "
    "probe_state, probe_detail, probed_at, created_at, updated_at, kind, computer_install_id"
)


def _agent_paths(raw: Optional[str]) -> Optional[Dict[str, str]]:
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        return None
    return value


def _hydrate(row) -> Host:
    return Host(
        key=str(row[0]), label=str(row[1]), ssh_target=row[2],
        ssh_port=int(row[3]) if row[3] is not None else None, socket=row[4],
        enabled=bool(row[5]), tmux_path=row[6], tmux_version=row[7],
        login_path=row[8], agent_paths=_agent_paths(row[9]), login_shell=row[10],
        machine_id=row[11], remote_carnivore=row[12], probe_state=str(row[13]),
        probe_detail=row[14], probed_at=row[15], created_at=str(row[16]),
        updated_at=str(row[17]), kind=str(row[18]), computer_install_id=row[19],
    )




def generate_key() -> str:
    return uuid.uuid4().hex


def validate_key(key: object) -> str:
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise HostInvalid("host_key_invalid",
                          "a host key is 1 to 32 of a-z, 0-9 and '-', starting with a letter or digit")
    if key == LOCAL_HOST_KEY:
        raise HostInvalid("host_key_reserved", "'local' is this machine and is reserved")
    return key


def validate_label(label: object) -> str:
    text = label.strip() if isinstance(label, str) else ""
    if not text or len(text) > LABEL_MAX or _CONTROL_RE.search(text):
        raise HostInvalid("host_label_invalid",
                          f"a label is 1 to {LABEL_MAX} characters with no control characters")
    return text


def validate_ssh_target(target: object) -> str:
    if (not isinstance(target, str) or len(target) > SSH_TARGET_MAX
            or not SSH_TARGET_RE.fullmatch(target)):
        raise HostInvalid(
            "host_target_invalid",
            "an ssh target is an alias or user@host: letters, digits, '.', '_', '+' and '-', "
            "each part starting with a letter, digit or '_'",
        )
    return target


def validate_ssh_port(port: object) -> Optional[int]:
    if port is None:
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise HostInvalid("host_port_invalid", "an ssh port is an integer from 1 to 65535")
    return port


def validate_socket(socket: object) -> str:
    if not isinstance(socket, str) or not SOCKET_RE.fullmatch(socket):
        raise HostInvalid("host_socket_invalid",
                          "a socket name is 1 to 64 of letters, digits, '_' and '-', "
                          "starting with a letter or digit")
    if socket in RESERVED_SOCKETS:
        raise HostInvalid("host_socket_reserved",
                          f"'{socket}' is the socket Carnivore runs its own sessions on; "
                          f"a remote host gets its own, like '{DEFAULT_REMOTE_SOCKET}'")
    return socket




def require_table(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, HOSTS_TABLE):
        raise HostsUnavailable("the hosts table is not present (schema before v40)")


def _row_for(conn: sqlite3.Connection, key: str):
    found = conn.execute(f"SELECT {_COLUMNS} FROM hosts WHERE key = ?", (str(key),)).fetchone()
    if found is None:
        raise HostNotFound(f"no host '{key}'")
    return found


def list_hosts(conn: sqlite3.Connection) -> List[Host]:
    require_table(conn)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM hosts ORDER BY key != 'local', key").fetchall()
    return [_hydrate(r) for r in rows]


def get_host(conn: sqlite3.Connection, key: str) -> Host:
    require_table(conn)
    return _hydrate(_row_for(conn, key))


def session_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT host_key, COUNT(*) FROM sessions WHERE archived_at IS NULL"
        + exclude_clause(conn) + " GROUP BY host_key"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _in_use(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sessions WHERE host_key = ? LIMIT 1", (key,)).fetchone() is not None




_KEY_GENERATION_ATTEMPTS = 5


def create_host(conn: sqlite3.Connection, *, label: str, ssh_target: str,
                ssh_port: Optional[int] = None, socket: Optional[str] = None,
                now: Optional[str] = None) -> Host:
    require_table(conn)
    label = validate_label(label)
    ssh_target = validate_ssh_target(ssh_target)
    ssh_port = validate_ssh_port(ssh_port)
    socket = validate_socket(DEFAULT_REMOTE_SOCKET if socket is None else socket)
    stamp = now or utc_now()
    with transaction(conn):
        for _ in range(_KEY_GENERATION_ATTEMPTS):
            key = generate_key()
            if conn.execute("SELECT 1 FROM hosts WHERE key = ?", (key,)).fetchone() is None:
                break
        else:
            raise HostKeyTaken("could not generate a free host key")
        conn.execute(
            "INSERT INTO hosts (key, label, ssh_target, ssh_port, socket, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, label, ssh_target, ssh_port, socket, stamp, stamp))
        host = _hydrate(_row_for(conn, key))
    roster_push.announce()
    return host


def update_host(conn: sqlite3.Connection, key: str, *, label: Optional[str] = None,
                enabled: Optional[bool] = None, socket: Optional[str] = None,
                now: Optional[str] = None) -> Host:
    require_table(conn)
    fields: Dict[str, object] = {}
    if label is not None:
        fields["label"] = validate_label(label)
    if enabled is not None:
        if not isinstance(enabled, bool):
            raise HostInvalid("host_enabled_invalid", "enabled is true or false")
        fields["enabled"] = 1 if enabled else 0
    if socket is not None:
        fields["socket"] = validate_socket(socket)
    with transaction(conn):
        current = _hydrate(_row_for(conn, key))
        if current.is_local:
            raise HostLocalFixed("'local' is this machine; it is never edited")
        if "socket" in fields and fields["socket"] != current.socket and _in_use(conn, key):
            raise HostInUse(f"sessions rows still name '{key}'; its socket cannot change under them")
        if fields:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            conn.execute(f"UPDATE hosts SET {assignments}, updated_at = ? WHERE key = ?",
                         (*fields.values(), now or utc_now(), key))
        host = _hydrate(_row_for(conn, key))
    roster_push.announce()
    return host


class ComputerUnknown(Exception):
    pass


def computer_known(conn: sqlite3.Connection, install_id: str) -> bool:
    if conn.execute("SELECT 1 FROM pack_machines WHERE install_id = ?", (install_id,)).fetchone() is not None:
        return True
    return conn.execute("SELECT 1 FROM hosts WHERE kind = 'peer' AND peer_install_id = ?", (install_id,)).fetchone() is not None


def link_computer(conn: sqlite3.Connection, key: str, install_id: Optional[str], *, now: Optional[str] = None) -> Host:
    require_table(conn)
    with transaction(conn):
        current = _hydrate(_row_for(conn, key))
        if current.is_local or current.kind != "ssh":
            raise HostLocalFixed("only an ssh host is linked to a computer")
        if install_id is not None and not computer_known(conn, install_id):
            raise ComputerUnknown(f"no computer '{install_id}'")
        conn.execute("UPDATE hosts SET computer_install_id = ?, updated_at = ? WHERE key = ?",
                     (install_id, now or utc_now(), key))
        host = _hydrate(_row_for(conn, key))
    roster_push.announce()
    return host


PROBE_COLUMNS = ("probe_state", "probe_detail", "login_shell", "login_path", "tmux_path",
                 "tmux_version", "agent_paths_json", "machine_id", "remote_carnivore")


def record_probe(conn: sqlite3.Connection, key: str, columns: Dict[str, Optional[str]], *,
                 now: Optional[str] = None) -> Host:
    if set(columns) != set(PROBE_COLUMNS):
        raise ValueError(f"a probe writes exactly {PROBE_COLUMNS}, got {sorted(columns)}")
    require_table(conn)
    stamp = now or utc_now()
    with transaction(conn):
        if _hydrate(_row_for(conn, key)).is_local:
            raise HostLocalFixed("'local' is this machine; it is never probed over ssh")
        assignments = ", ".join(f"{name} = ?" for name in PROBE_COLUMNS)
        conn.execute(f"UPDATE hosts SET {assignments}, probed_at = ?, updated_at = ? WHERE key = ?",
                     (*(columns[name] for name in PROBE_COLUMNS), stamp, stamp, key))
        host = _hydrate(_row_for(conn, key))
    roster_push.announce()
    return host


def delete_host(conn: sqlite3.Connection, key: str) -> None:
    require_table(conn)
    with transaction(conn):
        current = _hydrate(_row_for(conn, key))
        if current.is_local:
            raise HostLocalFixed("'local' is this machine; it is never deleted")
        if _in_use(conn, key):
            raise HostInUse(f"sessions rows still name '{key}'")
        conn.execute("DELETE FROM hosts WHERE key = ?", (key,))
    roster_push.announce()
