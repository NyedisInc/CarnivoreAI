"""Plan, and on request make, the move of the Task Manager's older files into the Task Manager folder (``docs/task-manager.md`` section 77, #1733).

Usage (a DRY RUN unless ``--apply``; nothing is written without it):

    venv/bin/python3 -m src.cplugs.huddle.cli.move_files_to_root \\
        --work-db "<state>/carnivore.db" --root /path/to/task-manager-folder \\
        [--projects-db "<state>/carnivore.db"] [--plugin-folder "<state>/cplugs/huddle"] [--apply]

The Task Manager's rows live in ``carnivore.db``'s ``work_`` tables (issue #1711, P2); the legacy ``huddle.db`` is a read-only
leftover this tool never reads. ``--plugin-folder`` (default: ``cplugs/huddle`` beside the database) is where the relative paths
resolve, so a dry run can read a COPY of the database while it only looks at the real files.

WHAT IT MOVES. Every file a reply or an artifact message names by a path RELATIVE to the plugin folder (section 42: ``files/<item
id>/<uuid8>-<name>``) goes to its task's folder, ``<root>/<project>/<task>/pastes/`` (or ``artifacts/`` for an artifact page), using the
same names and the same never-moved folders the app uses (``sdk/task_folders.py``). Each message's ``parts`` is rewritten to the ABSOLUTE
new path. A path already absolute is left alone, so a second run plans nothing. Files no message names (an upload never sent) stay
where they are: the orphan sweep owns them.

APPLY. Quit Carnivore first (the server writes the same file). ``--apply`` copies the database beside itself
(``carnivore.db.pre-move-files-<UTC>``) with sqlite's backup, then works item by item: its files move first, then its messages are
rewritten in one transaction, each only if its ``parts`` is still the value planned (a compare-and-set). A failure stops the run and
names the item; an item whose files moved but whose messages were not rewritten still serves them, because the app looks in the task
folder too (``files.locate``). The root must be an absolute real folder holding the ``.boards-root`` marker.

Exit codes: 0 done (or nothing to do), 1 a refusal or a failure, 2 could not read the inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO

from src.core.work import storage as work_storage
from src.cplugs.huddle import files, title
from src.cplugs.sdk import task_folders


class MoveError(Exception):
    pass


@dataclass(frozen=True)
class Move:

    item_id: int
    source: Path
    kind: str
    target: Path


@dataclass
class Plan:

    moves: List[Move] = field(default_factory=list)
    rewrites: Dict[int, tuple] = field(default_factory=dict)
    task: Dict[int, Path] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)


def check_root(text: str) -> Path:
    if not os.path.isabs(text):
        raise MoveError("--root must be an absolute path")
    path = Path(os.path.normpath(text))
    if os.path.realpath(path) != str(path) or not task_folders.is_real_dir(path):
        raise MoveError("--root must be a real folder (no symlink anywhere on the path)")
    if not (path / task_folders.ROOT_MARKER).is_file():
        raise MoveError(f"--root has no {task_folders.ROOT_MARKER} marker, so nothing is written there")
    return path


def read_projects(path: Optional[Path]) -> Dict[str, str]:
    if path is None:
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        return {str(row[0]): row[1] for row in conn.execute("SELECT id, display_name FROM projects")}


def _planned_task(root: Path, item: sqlite3.Row, projects: Dict[str, str]) -> Path:
    found = task_folders.find_task(root, item["id"])
    if found is not None:
        return found
    key = item["list_key"]
    project = task_folders.find_project(root, key) or root / task_folders.project_folder_name(key, projects.get(key))
    return project / task_folders.task_folder_name(item["id"], title.display(dict(item)))


def build_plan(db: Path, root: Path, projects: Dict[str, str], plugin: Optional[Path] = None) -> Plan:
    plugin = work_storage.folder(db.parent) if plugin is None else plugin
    plan = Plan()
    planned: Dict[Path, Path] = {}
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        items = {r["id"]: r for r in conn.execute("SELECT id, list_key, title, text FROM work_items")}
        rows = conn.execute(f"SELECT id, item_id, parts FROM work_messages WHERE {files.PARTS_SQL} ORDER BY id").fetchall()
    for row in rows:
        try:
            parsed = json.loads(row["parts"])
        except ValueError:
            plan.missing.append(f"message {row['id']}: parts is not JSON; left alone")
            continue
        artifact = (parsed.get("artifact") or {}).get("id") if isinstance(parsed.get("artifact"), dict) else None
        changed = False
        for entry in parsed.get("files", []) if isinstance(parsed, dict) else []:
            rel = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(rel, str) or os.path.isabs(rel) or row["item_id"] not in items:
                continue
            source = plugin / rel
            if source.is_symlink() or not source.is_file():
                plan.missing.append(f"item {row['item_id']}: {rel} is not on disk; its message is left alone")
                continue
            task = plan.task.setdefault(row["item_id"], _planned_task(root, items[row["item_id"]], projects))
            kind = task_folders.ARTIFACTS if entry.get("id") == artifact else task_folders.PASTES
            if source not in planned:
                planned[source] = task / kind / source.name
                plan.moves.append(Move(row["item_id"], source, kind, planned[source]))
            entry["path"] = str(planned[source])
            changed = True
        if changed:
            plan.rewrites[row["id"]] = (row["parts"], json.dumps(parsed, ensure_ascii=False))
    return plan


def render(plan: Plan, root: Path, out: TextIO) -> None:
    by_item: Dict[int, List[Move]] = {}
    for move in plan.moves:
        by_item.setdefault(move.item_id, []).append(move)
    for item_id, moves in sorted(by_item.items()):
        size = sum(m.source.stat().st_size for m in moves)
        kinds = ", ".join(f"{sum(1 for m in moves if m.kind == k)} {k}" for k in (task_folders.PASTES, task_folders.ARTIFACTS)
                          if any(m.kind == k for m in moves))
        print(f"item {item_id} -> {plan.task[item_id].relative_to(root)}/ : {kinds} ({size} bytes)", file=out)
    for note in plan.missing:
        print(f"note: {note}", file=out)
    total = sum(m.source.stat().st_size for m in plan.moves)
    print(f"total: {len(plan.moves)} files ({total} bytes) from {len(by_item)} tasks, {len(plan.rewrites)} messages rewritten", file=out)


def _backup(db: Path) -> Path:
    target = db.with_name(f"{db.name}.pre-move-files-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    with closing(sqlite3.connect(str(db))) as src, closing(sqlite3.connect(str(target))) as dst:
        src.backup(dst)
    return target


def apply(plan: Plan, db: Path, root: Path, projects: Dict[str, str], out: TextIO) -> None:
    print(f"backup: {_backup(db)}", file=out)
    message_items: Dict[int, int] = {}
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        for message_id in plan.rewrites:
            message_items[message_id] = conn.execute("SELECT item_id FROM work_messages WHERE id = ?", (message_id,)).fetchone()[0]
        items = {r[0]: r for r in conn.execute("SELECT id, list_key, title, text FROM work_items")}
    for item_id in sorted(plan.task):
        row = items[item_id]
        task = task_folders.ensure_task(root, item_id, row[1], projects.get(row[1]), title.display({"id": row[0], "title": row[2], "text": row[3]}))
        if task != plan.task[item_id]:
            raise MoveError(f"item {item_id}: the folder is {task}, not the planned {plan.task[item_id]}; run the dry run again")
        try:
            for move in (m for m in plan.moves if m.item_id == item_id):
                files.move_into(move.source, task_folders.kind_dir(task, move.kind))
        except OSError as exc:
            raise MoveError(f"item {item_id}: a file could not be moved ({exc}); its messages were not rewritten") from exc
        with closing(sqlite3.connect(str(db))) as conn, conn:
            for message_id, (old, new) in plan.rewrites.items():
                if message_items[message_id] == item_id:
                    conn.execute("UPDATE work_messages SET parts = ? WHERE id = ? AND parts = ?", (new, message_id, old))
        print(f"moved item {item_id}", file=out)


def main(argv: Optional[Sequence[str]] = None, out: TextIO = sys.stdout) -> int:
    """Run the command. Inputs: argv; out. Output: exit code (0 done, 1 refused or failed, 2 could not read the inputs)."""
    parser = argparse.ArgumentParser(description="move the huddle's older files into the Task Manager folder (dry run by default)")
    parser.add_argument("--work-db", type=Path, required=True, help="carnivore.db, which holds the Task Manager's work_ tables")
    parser.add_argument("--root", required=True)
    parser.add_argument("--projects-db", type=Path, default=None)
    parser.add_argument("--plugin-folder", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = check_root(args.root)
        projects = read_projects(args.projects_db)
        own_folder = work_storage.folder(args.work_db.parent)
        if args.apply and args.plugin_folder is not None and args.plugin_folder.resolve() != own_folder.resolve():
            raise MoveError("--apply works on the database's own Task Manager folder; --plugin-folder is for a dry run on a copy")
        plan = build_plan(args.work_db, root, projects, args.plugin_folder)
    except MoveError as exc:
        print(f"refused: {exc}", file=out)
        return 1
    except (OSError, sqlite3.Error) as exc:
        print(f"could not read the inputs: {exc}", file=out)
        return 2
    render(plan, root, out)
    if not args.apply:
        print("dry run: nothing was written (add --apply, with Carnivore quit, to make it)", file=out)
        return 0
    try:
        apply(plan, args.work_db, root, projects, out)
    except (MoveError, sqlite3.Error) as exc:
        print(f"stopped: {exc}", file=out)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
