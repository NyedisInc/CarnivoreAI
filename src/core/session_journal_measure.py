
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import conversation_writers as cw
from src.core.claude_resume_argv import SHARED_TABLE_MAX_AGE_SECONDS
from src.core.companion_shell.rows import exclude_clause
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.session_journal_observe import PaneFacts

logger = structlog.get_logger()

ROW_COLUMNS: Tuple[str, ...] = (
    "id", "session_uuid", "tmux_socket", "tmux_name", "tmux_created_epoch",
    "origin", "agent_type", "agent_family", "agent_family_source", "model",
    "claude_session_uuid", "working_dir", "title", "pinned_theme",
    "lifecycle", "lifecycle_source", "last_seen_running_at", "last_work_at",
    "archived_at",
)


@dataclass
class Measurement:
    """Everything one pass saw.

    Attributes:
        listing_ok / listing_complete: the tmux listing's own verdicts.
        listing_reason: ``no_server`` when there is no tmux server at all.
        panes: one PaneFacts per live pane.
        writers: every live claude process on the machine.
        rows: ``sessions`` rows with a tmux identity (dicts).
        groups: session_uuid -> group name.
        rows_ok: False when the database could not be read.
        writers_ok: False when ``ps`` could not run.
    """

    listing_ok: bool = False
    listing_complete: bool = False
    listing_reason: Optional[str] = None
    panes: List[PaneFacts] = field(default_factory=list)
    writers: List[cw.Writer] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    groups: Dict[str, str] = field(default_factory=dict)
    rows_ok: bool = False
    writers_ok: bool = False

    @property
    def server_running(self) -> bool:
        return self.listing_ok and self.listing_reason != "no_server"

    def live_instances(self) -> set:
        return {(p.name, p.epoch) for p in self.panes if not p.dead}

    def dead_instances(self) -> set:
        return {(p.name, p.epoch) for p in self.panes if p.dead}

    def rows_by_instance(self) -> Dict[Tuple[str, Optional[int]], Dict[str, Any]]:
        return {(r.get("tmux_name"), r.get("tmux_created_epoch")): r for r in self.rows}


def read_rows(db_path: Path) -> Tuple[bool, List[Dict[str, Any]], Dict[str, str]]:
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            scope, params = host_scope(conn, LOCAL_HOST_KEY)
            rows = [dict(r) for r in conn.execute(
                f"SELECT {', '.join(ROW_COLUMNS)} FROM sessions WHERE tmux_name IS NOT NULL"
                + scope + exclude_clause(conn), params
            )]
            groups = {
                r["session_uuid"]: r["name"] for r in conn.execute(
                    "SELECT m.session_uuid, g.name FROM session_group_membership m "
                    "JOIN session_groups g ON g.id = m.group_id"
                )
            }
        return True, rows, groups
    except sqlite3.Error as exc:
        logger.warning("session_journal_rows_unreadable", error=str(exc))
        return False, [], {}


def _pane_facts(pane: Dict[str, Any], table: Optional[cw.ProcessTable], by_pid: Dict[int, cw.Writer],
                row: Optional[Dict[str, Any]], is_claude, flag_signature) -> PaneFacts:
    dead = str(pane.get("pane_dead")) == "1"
    claude = None
    if table is not None and not dead and pane.get("pid"):
        claude = cw.first_claude_under(table, int(pane["pid"]), is_claude)
    writer = by_pid.get(claude.pid) if claude else None
    cwd = writer.cwd if writer and writer.cwd else None
    if cwd is None and row and row.get("working_dir"):
        cwd = os.path.realpath(row["working_dir"])
    return PaneFacts(
        name=pane["name"],
        epoch=pane.get("created_at_epoch"),
        dead=dead,
        claude_pid=claude.pid if claude else None,
        argv=claude.command if claude else None,
        observed_flags=sorted(flag_signature(claude.command)) if claude else None,
        conversation=writer.conversation if writer else None,
        conversation_source=writer.source if writer and writer.conversation else None,
        cwd=cwd,
    )


def measure(settings: Any, socket_name: str, db_path: Path) -> Measurement:
    from src.core.claude_resume_argv import is_claude_command
    from src.core.session_agent_infer import flag_signature
    from src.core.tmux_backend import TmuxBackend

    m = Measurement()
    try:
        probe = TmuxBackend.for_external(
            session_name="__session_journal__",
            working_dir=Path(settings.default_working_dir).expanduser(),
            on_output=None,
            socket_name=socket_name,
        )
        listing = probe.list_pane_status_all(fresh=True)
        m.listing_ok = bool(listing.ok)
        m.listing_complete = bool(listing.ok and listing.complete)
        m.listing_reason = listing.reason
        panes = list(listing.sessions or [])
    except (OSError, ValueError, AttributeError, RuntimeError) as exc:
        logger.warning("session_journal_listing_failed", error=str(exc))
        panes = []

    table: Optional[cw.ProcessTable] = None
    try:
        table = cw.read_process_table(max_age=SHARED_TABLE_MAX_AGE_SECONDS)
        m.writers = cw.live_writers(table, is_claude_command)
        m.writers_ok = True
    except cw.MeasureError as exc:
        logger.warning("session_journal_ps_failed", error=str(exc))

    m.rows_ok, m.rows, m.groups = read_rows(db_path)
    by_pid = {w.pid: w for w in m.writers}
    rows = m.rows_by_instance()
    m.panes = [
        _pane_facts(p, table, by_pid, rows.get((p.get("name"), p.get("created_at_epoch"))),
                    is_claude_command, flag_signature)
        for p in sorted(panes, key=lambda p: p.get("name") or "")
    ]
    return m
