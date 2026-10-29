
from __future__ import annotations

import hashlib
import socket
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple, TypeVar

from src.core.inventory.claims import DERIVED, GAP, GLOBAL, SECRET, TRANSIENT, ExcludedStore  # noqa: F401
from src.core.inventory.claude_folders import (  # noqa: F401
    FORM_CONFLICT,
    FORM_FOLDER,
    FORM_MAIN,
    FORM_SET_ASIDE,
    MERGED_SIDE_PREFIX,
    conversation_form,
)
from src.core.inventory.entry_claims import (  # noqa: F401
    CLAUDE_JSON_STORE,
    CONFIG_STORE,
    RENAME_STORE,
    UNREAD_STORE,
    claude_json_files,
)
from src.core.inventory.file_claims import (  # noqa: F401
    STORE_BACKUP_COPIES,
    STORE_DESK,
    STORE_FOLDER,
    STORE_MEMORY,
    STORE_ORPHANS,
    STORE_PIPE,
    STORE_POINTS,
    STORE_SWARM_HOOKS,
    STORE_SWARM_SETTINGS,
    STORE_TASK_FILES,
    STORE_THEME_DOTFILE,
)
from src.core.inventory.locations import PINNED_THEMES_FILE, Locations  # noqa: F401
from src.core.inventory.model import (  # noqa: F401
    KIND_DIR,
    KIND_ENTRY,
    KIND_FILE,
    KIND_LINES,
    KIND_ROWS,
    MAIN_STORE,
    ROLE_KEY,
    ROLE_PATH,
    ROLE_SECRET,
    SCOPE_PROJECT,
    SCOPE_SESSION,
    Artifact,
    FieldRef,
    Inventory,
    ProjectIdentity,
    SessionIdentity,
)
from src.core.inventory.registry_side import EXCLUDED_STORES, SIDE_DBS  # noqa: F401
from src.core.inventory.side_trace import JOURNAL, PREFERENCES  # noqa: F401
from src.core.inventory.plan_refs import plan_slugs  # noqa: F401
from src.core.inventory.vault_claims import STORE_VAULT  # noqa: F401
from src.core.message_model_secrets import ALL_DETECTORS  # noqa: F401
from src.core.project_move.plan import PaneListing  # noqa: F401
from src.cplugs.sdk.crate_rows import BATCH_ROWS, RowBatch, RowQuery, preflight, snapshot_rows  # noqa: F401
from src.cplugs.sdk.vault_sources import SourceUnavailable

T = TypeVar("T")
_SECRET_SOURCES = ("message_model_secrets.py", "message_model_secret_redaction.py")


class CrateTargetError(LookupError):

    def __init__(self, code: str, detail: str, candidates: Sequence[str] = ()) -> None:
        super().__init__(detail)
        self.code, self.detail, self.candidates = code, detail, list(candidates)


def locations() -> Locations:
    from src.config import settings
    from src.cplugs.sdk.transcript_files import config_file, state_dir

    return Locations(state_dir=state_dir(), config_path=config_file(),
                     pins_path=Path(settings.get_pinned_themes_path()),
                     unread_path=Path(settings.get_unread_state_path()))


def _with_main(state_dir: Path, work: Callable[[sqlite3.Connection], T]) -> T:
    """Run ``work`` on carnivore.db (never created). Raises SourceUnavailable when it cannot be opened or read."""
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    try:
        with closing(connect(db_path_for(Path(state_dir)), create=False)) as conn:
            return work(conn)
    except DatastoreUnreadableError as exc:
        raise SourceUnavailable(str(exc)) from exc
    except sqlite3.Error as exc:
        raise SourceUnavailable(f"cannot read carnivore.db: {exc}") from exc


def resolve(scope: str, target: str, locs: Locations, *, related_blockers: Optional[List[str]] = None) -> Inventory:
    from src.core.inventory.model import ProjectNotFound, SessionNotFound
    from src.core.inventory.plugin_claims import add_plugin_artifacts
    from src.core.inventory.resolve import resolve_project_target, resolve_session_target
    from src.core.inventory.target import TargetAmbiguous, TargetNotFound

    if scope not in (SCOPE_SESSION, SCOPE_PROJECT):
        raise ValueError(f"unknown scope {scope!r}")
    run = resolve_session_target if scope == SCOPE_SESSION else resolve_project_target
    try:
        return _with_main(locs.state_dir, lambda conn: add_plugin_artifacts(
            run(conn, target, locs, related_blockers=related_blockers), conn, locs))
    except TargetAmbiguous as exc:
        raise CrateTargetError("target_ambiguous", str(exc), exc.candidates) from exc
    except (TargetNotFound, SessionNotFound, ProjectNotFound) as exc:
        raise CrateTargetError("target_not_found", str(exc)) from exc


def declared_store_rels(locs: Locations) -> List[str]:
    from src.core.inventory.plugin_stores import declared_state_rels

    return declared_state_rels(locs)


def superseded_by_declaration(pattern: str, rels: Sequence[str]) -> bool:
    from src.core.inventory.plugin_stores import superseded

    return superseded(pattern, rels)


def live_panes() -> PaneListing:
    """Every live pane on Carnivore's tmux socket (``ok=False`` when the listing did not answer). Blocking."""
    from src.api.project_move_routes import read_live_panes

    return read_live_panes()


def live_blocker(ident: SessionIdentity, listing: PaneListing) -> Optional[str]:
    """Why the session counts as live, or None when measured asleep (a listing that did not answer refuses). Pure."""
    from src.core.session_purge.identity import live_blocker as purge_live_blocker

    return purge_live_blocker(ident, listing.ok, listing.panes)


def is_local_host(host_key: Optional[str]) -> bool:
    from src.core.session_purge.identity import LOCAL_HOST_KEYS

    return host_key in LOCAL_HOST_KEYS


def project_air_gapped(project_id: int, *, state_dir: Path) -> Optional[bool]:
    def read(conn: sqlite3.Connection) -> Optional[bool]:
        row = conn.execute("SELECT air_gap FROM projects WHERE id = ?", (project_id,)).fetchone()
        return None if row is None or row[0] is None else bool(row[0])

    try:
        return _with_main(state_dir, read)
    except SourceUnavailable:
        return None


def project_keys(project_id: int, *, state_dir: Path) -> Optional[Tuple[str, FrozenSet[str]]]:
    def read(conn: sqlite3.Connection) -> Optional[Tuple[str, FrozenSet[str]]]:
        row = conn.execute("SELECT uid FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        uuids = conn.execute("SELECT session_uuid FROM sessions WHERE project_id = ? AND session_uuid IS NOT NULL",
                             (project_id,)).fetchall()
        return str(row[0] or ""), frozenset(str(u[0]) for u in uuids)

    return _with_main(state_dir, read)


def install_identity(*, state_dir: Path) -> Tuple[Optional[str], str]:
    from src.core.db import get_meta
    from src.core.db_models import META_INSTALL_ID

    try:
        install_id = _with_main(state_dir, lambda conn: get_meta(conn, META_INSTALL_ID))
    except SourceUnavailable:
        install_id = None
    host = socket.gethostname()
    return install_id, host[:-len(".local")] if host.endswith(".local") else host


def app_version() -> str:
    from src.core.version import read_version_file

    return read_version_file() or "unknown"


def load_trust_map(path: Path) -> Optional[Dict[str, bool]]:
    from src.core.claude_folder_trust import load_trust_map as core_load

    return core_load(path)


def journal_entries(state_dir: Path, session_uuids: Set[str], row_ids: Set[int]) -> Optional[Dict[str, Any]]:
    from src.core.session_journal_store import LOAD_UNREADABLE, load_journal

    loaded = load_journal(Path(state_dir))
    if loaded.outcome == LOAD_UNREADABLE:
        return None

    def names(entry: Any) -> bool:
        return isinstance(entry, dict) and (entry.get("session_uuid") in session_uuids or entry.get("row_id") in row_ids)

    out: Dict[str, Any] = {}
    for part in ("sessions", "declined"):
        block = loaded.journal.get(part)
        out[part] = {k: v for k, v in block.items() if names(v)} if isinstance(block, dict) else {}
    return out


def scan_counts(text: str) -> Dict[str, int]:
    from src.core.message_model_secrets import scan_text

    return dict(Counter(f.detector for f in scan_text(text, trust_vendor_marker=True)))


def redact(text: str) -> str:
    from src.core.stream_redactor import redact_whole

    return redact_whole(text)


def detectors_digest() -> str:
    import src.core.message_model_secrets as secrets_module

    digest = hashlib.sha256("\n".join(sorted(ALL_DETECTORS)).encode("utf-8"))
    folder = Path(secrets_module.__file__).resolve().parent
    for name in _SECRET_SOURCES:
        digest.update(b"\0" + (folder / name).read_bytes())
    return digest.hexdigest()


def fallback_sources() -> Tuple[Any, ...]:
    from src.core.deepsearch.fallback_hook import sources

    return sources()


def backup_provider_id(locs: Locations) -> Optional[str]:
    from src.core.inventory.plugin_stores import backup_provider

    store = backup_provider(locs)
    return store.plugin_id if store is not None else None


def backup_families(inv: Inventory, locs: Locations) -> List[Dict[str, Any]]:
    from src.core.inventory.backup_families import backup_families as families

    return families(inv, locs)


def fork_relatives(row_ids: Sequence[int], *, state_dir: Path) -> List[Tuple[str, str]]:
    ids = sorted({int(r) for r in row_ids})
    if not ids:
        return []

    def read(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT c.session_uuid, p.session_uuid FROM sessions c JOIN sessions p ON p.id = c.parent_session_id "
            f"WHERE c.id IN ({marks}) AND p.id NOT IN ({marks}) ORDER BY c.session_uuid, p.session_uuid", ids + ids)
        return [(str(a), str(b)) for a, b in rows]

    return _with_main(state_dir, read)


__all__ = [
    "DERIVED", "GAP", "GLOBAL", "SECRET", "TRANSIENT", "ExcludedStore",
    "FORM_CONFLICT", "FORM_FOLDER", "FORM_MAIN", "FORM_SET_ASIDE", "MERGED_SIDE_PREFIX", "conversation_form",
    "CLAUDE_JSON_STORE", "CONFIG_STORE", "RENAME_STORE", "UNREAD_STORE", "claude_json_files",
    "STORE_BACKUP_COPIES", "STORE_DESK", "STORE_FOLDER", "STORE_MEMORY", "STORE_ORPHANS", "STORE_PIPE", "STORE_POINTS",
    "STORE_SWARM_HOOKS", "STORE_SWARM_SETTINGS", "STORE_TASK_FILES", "STORE_THEME_DOTFILE", "STORE_VAULT",
    "PINNED_THEMES_FILE", "Locations",
    "KIND_DIR", "KIND_ENTRY", "KIND_FILE", "KIND_LINES", "KIND_ROWS", "MAIN_STORE", "ROLE_KEY", "ROLE_PATH", "ROLE_SECRET",
    "SCOPE_PROJECT", "SCOPE_SESSION", "Artifact", "FieldRef", "Inventory", "ProjectIdentity", "SessionIdentity",
    "EXCLUDED_STORES", "SIDE_DBS", "JOURNAL", "PREFERENCES", "ALL_DETECTORS", "PaneListing",
    "BATCH_ROWS", "RowBatch", "RowQuery", "preflight", "snapshot_rows", "SourceUnavailable", "CrateTargetError",
    "locations", "resolve", "declared_store_rels", "superseded_by_declaration", "live_panes", "live_blocker", "is_local_host", "project_air_gapped", "install_identity",
    "app_version", "load_trust_map", "journal_entries", "scan_counts", "redact", "detectors_digest", "fallback_sources", "backup_provider_id", "backup_families",
    "fork_relatives", "plan_slugs",
]
