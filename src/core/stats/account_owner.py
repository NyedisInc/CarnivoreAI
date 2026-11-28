from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core.agy import accounts as agy_accounts
from src.core.agy.state import state_for_conversation
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.provider_ledger import accounts_store, poller, poller_scan
from src.core.provider_ledger.default_login import canonical_path
from src.core.session_token_usage.account_resolve import accounts_for_default_login
from src.core.stats.plugin import extract, usage_revision
from src.core.stats.store_port import StatsStoreLike


logger = structlog.get_logger()
_TTL_SECONDS = 120
_PROJECT_TTL_SECONDS = 60
_DEFAULT_TIER = 0
_MANAGED_TIER = 1


def sessions_seen(profile: Path) -> dict[str, float]:
    seen: dict[str, float] = {}
    try:
        with (profile / "history.jsonl").open("rb") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                sid = row.get("sessionId") if isinstance(row, dict) else None
                stamp = row.get("timestamp") if isinstance(row, dict) else None
                if isinstance(sid, str) and isinstance(stamp, (int, float)):
                    seen[sid] = max(seen.get(sid, 0.0), stamp / 1000)
    except OSError:
        pass
    try:
        with os.scandir(profile / "session-env") as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    seen[entry.name] = max(seen.get(entry.name, 0.0), entry.stat().st_mtime)
    except OSError:
        pass
    return seen


def build_index(accounts: list[ProviderAccount]) -> dict[str, tuple[int, float, str]]:
    index: dict[str, tuple[int, float, str]] = {}
    default_dir = canonical_path("~/.claude")
    default_owner = accounts_for_default_login(accounts, provider="claude")
    plans: list[tuple[Path, int, str]] = []
    for account in accounts:
        if account.provider != "claude":
            continue
        directory = canonical_path(profile_dir_for(account))
        if directory is not None and directory != default_dir:
            plans.append((Path(directory), _MANAGED_TIER, account.id))
    if default_dir is not None and len(default_owner) == 1:
        plans.append((Path(default_dir), _DEFAULT_TIER, default_owner[0].id))
    for directory, tier, account_id in plans:
        for sid, stamp in sessions_seen(directory).items():
            if sid not in index or (tier, stamp) > index[sid][:2]:
                index[sid] = (tier, stamp, account_id)
    return index


def build_codex_roots(accounts: list[ProviderAccount]) -> list[tuple[str, str]]:
    roots: list[tuple[str, str]] = []
    seen_dirs: set[str] = set()
    for account in accounts:
        if account.provider != "codex":
            continue
        directory = canonical_path(profile_dir_for(account))
        if directory and directory not in seen_dirs:
            seen_dirs.add(directory)
            roots.append((directory, account.id))
    roots.sort(key=lambda item: len(item[0]), reverse=True)
    return roots


def _ledger_provider_ids(provider: str) -> list[str]:
    try:
        snap = poller.snapshot()
    except Exception:  # noqa: BLE001
        return []
    return sorted({a.id for a in snap.accounts if a.provider == provider and a.id})


class AccountAttribution:

    def __init__(self, config_path: Path, state_dir: Optional[Path] = None) -> None:
        self.config_path = config_path
        self.state_dir = Path(state_dir) if state_dir is not None else None
        self._index: dict[str, tuple[int, float, str]] = {}
        self._codex_roots: list[tuple[str, str]] = []
        self._codex_ids: list[str] = []
        self._agy_ids: list[str] = []
        self._built = 0.0
        self._lock = threading.Lock()

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and time.monotonic() - self._built < _TTL_SECONDS:
                return
            try:
                accounts = poller_scan.with_auto_default(accounts_store.list_accounts(self.config_path))
                self._index = build_index(accounts)
                self._codex_roots = build_codex_roots(accounts)
                self._codex_ids = sorted({a.id for a in accounts if a.provider == "codex"})
                configured_agy = {a.id for a in accounts if a.provider == "antigravity"}
                self._agy_ids = sorted(configured_agy or set(_ledger_provider_ids("antigravity")))
            except (OSError, ValueError) as exc:
                logger.warning("stats_account_index_failed", error_type=type(exc).__name__)
            self._built = time.monotonic()

    def _resolve_codex(self, path: Optional[str]) -> Optional[str]:
        if path:
            real = canonical_path(path)
            if real:
                for root, account_id in self._codex_roots:
                    if real == root or real.startswith(root + os.sep):
                        return account_id
        if len(self._codex_ids) == 1:
            return self._codex_ids[0]
        return None

    def _resolve_antigravity(self, root_cid: str) -> Optional[str]:
        if self.state_dir is not None:
            state = state_for_conversation(self.state_dir, root_cid)
            email = state.get("email") if isinstance(state, dict) else None
            if isinstance(email, str) and email.strip():
                try:
                    return agy_accounts.account_id_for_email(email)
                except agy_accounts.AgyAccountError:
                    pass
        if len(self._agy_ids) == 1:
            return self._agy_ids[0]
        return None

    def __call__(self, provider: str, conversation_id: str, path: Optional[str] = None) -> Optional[str]:
        root_cid = conversation_id.split(":", 1)[0]
        self.refresh()
        if provider == "claude":
            hit = self._index.get(root_cid)
            return hit[2] if hit else None
        if provider == "codex":
            return self._resolve_codex(path)
        if provider in ("antigravity", "agy"):
            return self._resolve_antigravity(root_cid)
        return None


class ProjectAttribution:

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self._cwds: dict[str, str] = {}
        self._built = 0.0
        self._lock = threading.Lock()

    def _refresh_sessions(self) -> None:
        with self._lock:
            if time.monotonic() - self._built < _PROJECT_TTL_SECONDS:
                return
            mapping: dict[str, str] = {}
            try:
                app_db = connect(db_path_for(self.state_dir), create=False)
            except DatastoreUnreadableError:
                self._built = time.monotonic()
                return
            try:
                rows = app_db.execute(
                    "SELECT claude_session_uuid, working_dir FROM sessions "
                    "WHERE claude_session_uuid IS NOT NULL AND claude_session_uuid != '' "
                    "AND working_dir IS NOT NULL AND working_dir != '' ORDER BY id"
                ).fetchall()
                for cid, cwd in rows:
                    mapping[cid] = cwd
            except sqlite3.Error as exc:
                logger.debug("stats_project_index_failed", error=str(exc))
            finally:
                app_db.close()
            self._cwds = mapping
            self._built = time.monotonic()

    def __call__(self, provider: str, conversation_id: str) -> Optional[str]:
        root_cid = conversation_id.split(":", 1)[0]
        if provider in ("antigravity", "agy"):
            state = state_for_conversation(self.state_dir, root_cid)
            cwd = state.get("cwd") if isinstance(state, dict) else None
            if isinstance(cwd, str) and cwd.strip():
                return cwd.strip()
        self._refresh_sessions()
        return self._cwds.get(root_cid)


def backfill_unattributed_accounts(store: StatsStoreLike, resolver: AccountAttribution) -> int:
    from src.core.pipeline import plugin_db

    resolver.refresh()
    with plugin_db.lock_for("stats"):
        with store.connect() as conn:
            pending = conn.execute(
                "SELECT id, path_key, provider, conversation_id FROM dim_source WHERE account_id IS NULL"
            ).fetchall()
            if not pending:
                return 0
            path_by_key = {
                extract.path_key(row[0]): row[0]
                for row in conn.execute("SELECT path FROM plugin_cursors").fetchall()
            }
            updates: list[tuple[str, int]] = []
            for src_id, path_key, provider, conversation_id in pending:
                account = resolver(provider, conversation_id, path_by_key.get(path_key))
                if account:
                    updates.append((account, src_id))
            if not updates:
                return 0
            conn.executemany("UPDATE dim_source SET account_id = ? WHERE id = ?", updates)
            usage_revision.bump(conn)
            conn.execute("UPDATE stats_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
            return len(updates)


_AGY_HEAD_LINES = 10
_AGY_HEAD_BYTES = 128 * 1024


def _sniff_agy_parent(path: str, self_id: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            read_bytes = 0
            for _ in range(_AGY_HEAD_LINES):
                raw = handle.readline(_AGY_HEAD_BYTES)
                if not raw:
                    break
                read_bytes += len(raw)
                if read_bytes > _AGY_HEAD_BYTES:
                    break
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") == "USER_INPUT":
                    return None
                parent = extract.agy_parent_from_record(obj, self_id)
                if parent:
                    return parent
    except OSError:
        return None
    return None


def backfill_subagent_parents(store: StatsStoreLike, project_resolver: Optional[ProjectAttribution] = None) -> int:
    from src.core.pipeline import plugin_db
    from src.core.stats import agent_names

    with plugin_db.lock_for("stats"):
        with store.connect() as conn:
            changed = 0
            cur = conn.execute(
                "UPDATE dim_source SET agent_kind = 'subagent' "
                "WHERE parent_conversation_id IS NOT NULL AND parent_conversation_id != '' AND agent_kind != 'subagent'"
            )
            changed += cur.rowcount

            agy_pending = conn.execute(
                "SELECT id, path_key, conversation_id FROM dim_source "
                "WHERE provider = 'antigravity' AND parent_conversation_id IS NULL AND agent_kind = 'session'"
            ).fetchall()
            if agy_pending:
                path_by_key = {
                    extract.path_key(row[0]): row[0]
                    for row in conn.execute("SELECT path FROM plugin_cursors WHERE family = 'agy'").fetchall()
                }
                parent_updates: list[tuple[str, int]] = []
                for src_id, path_key, cid in agy_pending:
                    transcript = path_by_key.get(path_key)
                    if not transcript:
                        continue
                    parent = _sniff_agy_parent(transcript, cid)
                    if parent:
                        parent_updates.append((parent, src_id))
                if parent_updates:
                    conn.executemany(
                        "UPDATE dim_source SET parent_conversation_id = ?, agent_kind = 'subagent' WHERE id = ?",
                        parent_updates,
                    )
                    changed += len(parent_updates)

            empty_proj_row = conn.execute("SELECT id FROM dim_project WHERE name = ''").fetchone()
            if empty_proj_row is not None and project_resolver is not None:
                empty_proj_id = empty_proj_row[0]
                parent_map = {
                    cid.split(":", 1)[0]: p.split(":", 1)[0]
                    for cid, p in conn.execute(
                        "SELECT conversation_id, parent_conversation_id FROM dim_source "
                        "WHERE parent_conversation_id IS NOT NULL AND parent_conversation_id != ''"
                    ).fetchall()
                }
                agy_subs = conn.execute(
                    "SELECT DISTINCT s.id, s.conversation_id FROM dim_source s "
                    "WHERE s.provider = 'antigravity' AND s.parent_conversation_id IS NOT NULL "
                    "AND (EXISTS (SELECT 1 FROM usage_minute u WHERE u.src = s.id AND u.project = ?) "
                    "  OR EXISTS (SELECT 1 FROM usage_hour u WHERE u.src = s.id AND u.project = ?))",
                    (empty_proj_id, empty_proj_id),
                ).fetchall()
                for src_id, cid in agy_subs:
                    root_cid = agent_names.root_of(cid, parent_map)
                    cwd = project_resolver("antigravity", root_cid)
                    if not cwd:
                        continue
                    pkey = extract.project_key(cwd)
                    conn.execute("INSERT OR IGNORE INTO dim_project(name) VALUES (?)", (pkey,))
                    target_proj_id = conn.execute("SELECT id FROM dim_project WHERE name = ?", (pkey,)).fetchone()[0]
                    if target_proj_id == empty_proj_id:
                        continue
                    for tbl in ("usage_minute", "usage_hour", "counter_minute", "counter_hour"):
                        try:
                            upd = conn.execute(
                                f"UPDATE OR IGNORE {tbl} SET project = ? WHERE src = ? AND project = ?",
                                (target_proj_id, src_id, empty_proj_id),
                            )
                            changed += upd.rowcount
                        except sqlite3.Error:
                            pass

            if changed > 0:
                usage_revision.bump(conn)
                conn.execute("UPDATE stats_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")
                agent_names.forget()
            return changed
