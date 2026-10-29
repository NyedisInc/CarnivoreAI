#!/usr/bin/env python3
"""Plan (read only, never apply) the import of a real crate into a THROWAWAY install and print the project action, the conversations (class and reason), the files left in the crate, the plugin-data and backup-family lines.

Usage: CARNIVORE_STATE_DIR=<temp dir> venv/bin/python3 tests/python/crate_import/probes/import_plan_probe.py <crate file> [--original]

``--original`` plans the restore into the crate's own project folder (the restore dialog's default), judged against the real home folder.

It lives under tests/ (not src/ or scripts/) because it builds the save plugin's backup source and vault and drives core directly, and neither a plugin nor production code may import across that boundary.

The throwaway install is built under ``CARNIVORE_STATE_DIR`` (refused when it is the live state folder, or when it already holds a
database). The review board plugin is ON, its ``boardsRoot`` is blank and the save plugin is ON with an empty vault, so the output is what a
fresh install with the default boards folder would show. The crate file is only read. Exit 0 = planned, 1 = the plan is blocked, 2 = bad input.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


class RefusedState(Exception):
    pass


def throwaway_env(base: Path):
    base = base.resolve()
    state = base / "state"
    live = (Path.home() / "Library" / "Application Support" / "Carnivore").resolve()
    if base == live or live in base.parents or (state / "carnivore.db").exists():
        raise RefusedState(f"{state} is the live state folder or already holds a database")
    from src.core.crate_import.env import ImportEnv  # noqa: PLC0415
    from src.core.db_migration import ensure_db_migrated
    from src.core.deepsearch import fallback_hook
    from src.core.inventory.locations import Locations
    from src.core.project_move.plan import PaneListing
    from src.core.work.storage import storage_for
    from src.cplugs.registry import CPLUGS
    from src.cplugs.save.fallback import BackupTranscripts
    from src.cplugs.save.vault.store import Vault
    from src.cplugs.sdk.crate_import import plugin_enabled_of, plugin_homes_of

    projects, claude, codex, vault_root = base / "projects", base / "claude", base / "codex", base / "vault"
    for folder in (state, projects, claude / "projects", codex, vault_root):
        folder.mkdir(parents=True, exist_ok=True)
    (vault_root / "VAULT.json").write_text('{"format": 1}')
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    storage_for(state).connect(True).close()
    config = state / "config.json"
    config.write_text("{}")
    manifests = tuple(d.manifest for d in CPLUGS)
    locations = Locations(state_dir=state, config_path=config, homes=(claude,), codex=codex, plugin_manifests=manifests,
                          plugin_settings={"reviewboard": {"boardsRoot": ""}}, plugin_enabled={"reviewboard": True, "save": True})
    vault = Vault(vault_root)
    fallback_hook.register("probe-save", BackupTranscripts(vault=lambda: vault))
    env = ImportEnv(state=state, projects_dir=str(projects), claude_homes=(claude,), codex_home=codex, install_id=None,
                    panes=lambda: PaneListing(True), writers=lambda: (), free_bytes=lambda path: 10**12, config_path=config,
                    plugin_homes=plugin_homes_of(locations), plugin_enabled=plugin_enabled_of(locations),
                    backup_sources=lambda: [BackupTranscripts(vault=lambda: vault)])
    return env, state, projects


def main(argv: List[str]) -> int:
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--original") or not os.environ.get("CARNIVORE_STATE_DIR"):
        print(__doc__)
        return 2
    try:
        env, state, projects = throwaway_env(Path(os.environ["CARNIVORE_STATE_DIR"]))
    except RefusedState as exc:
        print(f"refused: {exc}")
        return 2
    from src.core.crate_format.reader import open_crate  # noqa: PLC0415
    from src.core.crate_import.model import ImportRequest
    from src.core.crate_import.plan import build_plan
    crate = Path(argv[0])
    sha = hashlib.sha256(crate.read_bytes()).hexdigest()
    with open_crate(crate) as reader:
        relocate = {"mode": "same_paths"} if len(argv) == 2 else {"mode": "relocate", "new_root": str(projects / "moved")}
        first = build_plan(reader, env, ImportRequest(**relocate), crate_sha256=sha, encrypted=False)
        units = sorted({str(r["unit"]) for r in first.get("backups", {}).get("folders", [])})
        request = ImportRequest(**relocate, include_plugin_data=True, file_backup_units=tuple(units))
        plan = build_plan(reader, env, request, crate_sha256=sha, encrypted=False)
    print(f"landing root_to={(plan.get('project') or {}).get('root_to')} root_from={(plan.get('project') or {}).get('root_from')}")
    print(f"plan ok={plan['ok']} provenance={plan.get('provenance')} blockers={plan.get('blockers')}")
    print(f"project action={(plan.get('project') or {}).get('action')}")
    for c in plan.get("conversations", []):
        print(f"conversation id={c['id']} class={c['class']} reason={c.get('reason')} title={c.get('title')}")
    for n in plan.get("not_restored", []):
        if n["what"].startswith("files:"):
            print(f"not_restored what={n['what']} why={n['why']}")
    for s in plan.get("plugin_data", []):
        print(f"plugin_data store={s.get('store')} decision={s.get('decision')} reason={s.get('reason')} files={s.get('files')} boards={len(s.get('boards') or [])}")
    backups = plan.get("backups", {})
    print(f"backups provider_enabled={backups.get('provider_enabled')} carried={backups.get('carried')} restores_folders={backups.get('restores_folders')}")
    for r in backups.get("folders", []):
        print(f"family unit={r['unit']} status={r['status']} reason={r['reason']} points={r['points']} files={r['files']}")
    print(f"default folder exists after the plan: {(state / 'review-boards').exists()} (a plan writes nothing)")
    return 0 if plan["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
