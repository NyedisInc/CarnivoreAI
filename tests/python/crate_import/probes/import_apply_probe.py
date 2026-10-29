#!/usr/bin/env python3
"""Plan and APPLY the import of a real crate into a THROWAWAY install and print what it wrote. Never the live state folder.

Usage: CARNIVORE_STATE_DIR=<temp dir> venv/bin/python3 tests/python/crate_import/probes/import_apply_probe.py <crate file> [project name]

The install comes from ``import_plan_probe.throwaway_env``. A project named ``[project name]`` (default ``Mindustry3``) is seeded at
``<projects>/<name>`` first, so the crate restores in relocate mode into a project that already exists, as on a second restore. The crate
file is only read. Exit 0 = applied, 1 = the plan is blocked or the apply failed, 2 = bad input.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: List[str]) -> int:
    if not argv or len(argv) > 2 or not os.environ.get("CARNIVORE_STATE_DIR"):
        print(__doc__)
        return 2
    from import_plan_probe import RefusedState, throwaway_env  # noqa: PLC0415
    from src.core.crate_format.reader import open_crate
    from src.core.crate_import import apply as ap
    from src.core.crate_import.model import ImportFailed, ImportRequest, new_import_id
    from src.core.crate_import.plan import build_plan
    from src.core.db import connect, db_path_for
    from tests.python.session_purge.purge_world import insert

    try:
        env, state, projects = throwaway_env(Path(os.environ["CARNIVORE_STATE_DIR"]))
    except RefusedState as exc:
        print(f"refused: {exc}")
        return 2
    name = argv[1] if len(argv) == 2 else "Mindustry3"
    target = projects / name
    target.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path_for(state))) as conn:
        insert(conn, "projects", uid="seed-uid", display_name=name, root=str(target), raw_path=str(target), source="user",
               created_at="now", updated_at="now")
        conn.commit()
    crate = Path(argv[0])
    sha = hashlib.sha256(crate.read_bytes()).hexdigest()
    with open_crate(crate) as reader:
        first = build_plan(reader, env, ImportRequest(mode="relocate", new_root=str(target)), crate_sha256=sha, encrypted=False)
        units = tuple(sorted({str(r["unit"]) for r in first.get("backups", {}).get("folders", [])}))
        request = ImportRequest(mode="relocate", new_root=str(target), include_plugin_data=True, include_project_files=True,
                                include_instructions=True, keep_conversations=True, file_backups=True, file_backup_units=units)
        plan = build_plan(reader, env, request, crate_sha256=sha, encrypted=False)
        print(f"plan ok={plan['ok']} blockers={plan.get('blockers')}")
        if not plan["ok"]:
            return 1
        try:
            receipt = ap.apply_import(reader, env, request, crate_sha256=sha, fingerprint=plan["fingerprint"], import_id=new_import_id())
        except ImportFailed as exc:
            print(f"apply FAILED: {exc}")
            _leftovers(state)
            return 1
    print(f"apply state={receipt.state} import_id={receipt.import_id}")
    for key, counts in sorted(receipt.rows.items()):
        print(f"rows {key}: {counts}")
    print(f"plugin_data={json.dumps(receipt.plugin_data, default=str)[:1500]}")
    print(f"backups={json.dumps(receipt.backups, default=str)[:800]}")
    print(f"warnings={[w.get('code') for w in receipt.warnings]}")
    return 0


def _leftovers(state: Path) -> None:
    with closing(sqlite3.connect(state / "carnivore.db")) as conn:
        for table in ("work_items", "work_messages", "sessions", "projects"):
            print(f"after failure {table}: {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
