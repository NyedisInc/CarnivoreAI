
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.core.inventory import locations
from src.cplugs.host.data_roots import VaultFolder
from src.core.inventory.registry_side import DEEPSEARCH, READER_STATE, SIDE_DBS, SKILL_FIRES, STATS

DERIVED_SIDE_DBS = frozenset({DEEPSEARCH, STATS, READER_STATE, SKILL_FIRES})


class SourceUnavailable(RuntimeError):
    """The install's database could not be read (missing, locked, unreadable)."""


def claude_roots() -> Tuple[Path, ...]:
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    return tuple(claude_transcript_roots())


def codex_home() -> Path:
    return locations.codex_home()


def vault_folders(state_dir: Path) -> List[VaultFolder]:
    from src.cplugs.host.data_roots import vault_folders as resolve  # noqa: PLC0415

    return resolve(Path(state_dir))


def plugin_name_keys() -> Dict[str, str]:
    from src.cplugs.host import runtime  # noqa: PLC0415

    return {d.id: d.manifest.name_key for d in runtime.definitions()}


def side_databases(state_dir: Path) -> List[Tuple[str, Path]]:
    found = [(name, Path(state_dir) / rel) for name, rel in SIDE_DBS.items() if name not in DERIVED_SIDE_DBS]
    return sorted((n, p) for n, p in found if p.is_file())


def _connect_readonly(state_dir: Path) -> sqlite3.Connection:
    from src.core.db import db_path_for

    path = db_path_for(Path(state_dir))
    try:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except (sqlite3.Error, OSError) as exc:
        raise SourceUnavailable(f"cannot open {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def manifest_rows(state_dir: Path) -> List[Dict[str, Any]]:
    try:
        with closing(_connect_readonly(state_dir)) as conn:
            cursor = conn.execute("SELECT path, family, kind, conversation_id, size, mtime_ns, status, dataless, changed_at, "
                                  "gone_at FROM transcript_files")
            return [dict(r) for r in cursor]
    except sqlite3.Error as exc:
        raise SourceUnavailable(f"cannot read the transcript manifest: {exc}") from exc


def project_roots(state_dir: Path) -> List[Dict[str, Any]]:
    try:
        with closing(_connect_readonly(state_dir)) as conn:
            rows = [dict(r) for r in conn.execute("SELECT uid, root, display_name, archived_at FROM projects WHERE root IS NOT NULL")]
    except sqlite3.Error as exc:
        raise SourceUnavailable(f"cannot read the projects table: {exc}") from exc
    return sorted(rows, key=lambda r: len(r["root"] or ""), reverse=True)


__all__ = ["DERIVED_SIDE_DBS", "SourceUnavailable", "claude_roots", "codex_home", "manifest_rows", "project_roots", "side_databases"]
