
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.core.companion_shell.rows import companion_labels, shell_label
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from src.core.project_move.paths import is_within, prefix_params, prefix_where
from src.core.project_move.plan import LOCAL_HOST, PaneListing
from src.core.project_pack import archive_io, git_check, inventory, store
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.inventory import InventoryError, Tree
from src.core.project_pack.plan import PackPlan

DEVELOPMENT_DIR = "Development"
APP_SUPPORT_NAMES = ("Carnivore", "Carnivore Menubar", "CloudeCode")


def forbidden_reason(root: str, env: PackEnv) -> str:
    home = os.path.realpath(Path.home())
    if root == home:
        return "this is the home folder"
    if os.path.dirname(root) == home and os.path.basename(root).startswith("."):
        return "this is a dot folder of the home folder (settings and credentials live there)"
    if root == os.path.realpath(os.path.join(home, DEVELOPMENT_DIR)):
        return "this is the Development folder, which holds every project"
    protected = [os.path.realpath(p) for p in (env.extra_forbidden or ())]
    protected += [os.path.realpath(Path(__file__).resolve().parents[3])]
    if env.state_dir:
        protected.append(os.path.realpath(env.state_dir))
    protected += [os.path.realpath(os.path.join(home, "Library", "Application Support", n)) for n in APP_SUPPORT_NAMES]
    protected += [os.path.realpath(p) for p in env.transcript_roots()]
    for path in protected:
        if is_within(path, root) or is_within(root, path):
            return f"this folder holds or sits inside Carnivore or Claude's own data ({path})"
    return ""


def _children(conn: sqlite3.Connection, project: Dict[str, Any]) -> List[sqlite3.Row]:
    sql = f"SELECT * FROM projects WHERE {prefix_where('root')} AND id != :pid AND host_key = :host"
    return conn.execute(sql, {**prefix_params(project["root"]), "pid": project["id"], "host": LOCAL_HOST}).fetchall()


def _live_sessions(conn: sqlite3.Connection, root: str, panes: PaneListing) -> Dict[str, str]:
    sql = f"SELECT * FROM sessions WHERE {prefix_where('working_dir')} AND host_key = :host"
    rows = conn.execute(sql, {**prefix_params(root), "host": LOCAL_HOST}).fetchall()
    live: Dict[str, str] = {}
    labels = companion_labels(conn)
    instances = {(r["tmux_name"], r["tmux_created_epoch"]) for r in rows if r["tmux_name"]}
    for r in rows:
        if r["lifecycle"] != SESSION_LIFECYCLE_STOPPED:
            name = r["tmux_name"] or r["title"] or r["session_uuid"]
            live.setdefault(shell_label(name, labels), r["lifecycle"])
    for name, epoch, cwd in panes.panes:
        if (name, epoch) in instances or (cwd and is_within(cwd, root)):
            live.setdefault(shell_label(name, labels), "live pane")
    return live


def _walk_checks(plan: PackPlan, tree: Tree | None, walk_error: str, env: PackEnv) -> None:
    if tree is None:
        why = walk_error or "not measured: the folder could not be walked"
        for check_id in ("readable", "not_empty", "no_transcripts", "no_cloud_only", "free_space"):
            plan.check(check_id, False, why)
        return
    plan.check("readable", not tree.unreadable, "every entry could be read" if not tree.unreadable
               else "could not read: " + ", ".join(tree.unreadable[:5]))
    plan.check("not_empty", bool(tree.entries), "the folder has content to pack" if tree.entries
               else "the folder is empty: nothing to pack")
    hits = tree.transcript_hits
    plan.check("no_transcripts", not hits, "no Claude transcript storage inside" if not hits
               else "Claude transcripts are inside: " + ", ".join(hits[:3]))
    n = tree.dataless
    plan.check("no_cloud_only", n == 0, "every file is downloaded" if n == 0 else
               f"{n} files are in iCloud only ({', '.join(tree.dataless_paths[:3])}); in Finder choose "
               "Download Now on this folder, then plan again")
    need, free = tree.logical_bytes + env.margin, env.free_bytes(plan.root)
    plan.check("free_space", free >= need, f"{free} bytes free, {need} needed")


def _git_checks(plan: PackPlan, root: str, accept_local_only: bool) -> List[git_check.RepoReport]:
    reports = git_check.inspect_all(root)
    plan.repos = [r.as_dict() for r in reports]
    bad = [f"{r.path}: {p}" for r in reports for p in r.problems]
    plan.check("git_clean", not bad, f"{len(reports)} git repos clean and pushed" if not bad else
               "git work would be lost: " + "; ".join(bad))
    plan.local_only = [f"{r.path}: {m}" for r in reports for m in r.local_only]
    plan.check("git_local_only", accept_local_only or not plan.local_only,
               "nothing exists only in the folder" if not plan.local_only else
               ("accepted: the archive will be the only copy of " if accept_local_only else
                "the archive would be the only copy of: ") + "; ".join(plan.local_only) +
               ("" if accept_local_only else " (resend with accept_local_only to allow it)"))
    for r in reports:
        plan.warnings += [f"{r.path}: {w}" for w in r.warnings]
    return reports


def build_pack_plan(conn: sqlite3.Connection, project: Dict[str, Any], *, panes: PaneListing, env: PackEnv,
                    accept_local_only: bool = False) -> PackPlan:
    root = project["root"]
    plan = PackPlan("pack", {"id": project["id"], "name": project["display_name"], "root": root})
    plan.check("archived", project["archived_at"] is not None, "the project is hidden (archived)" if
               project["archived_at"] else "hide (archive) the project first; only hidden projects can be packed")
    state = store.state_of(conn, project["id"])
    plan.check("state_unpacked", state == K.STATE_UNPACKED, "the folder is not packed" if state == K.STATE_UNPACKED
               else f"the project is {state}")
    real_dir = os.path.isdir(root) and not os.path.islink(root) and os.path.realpath(root) == root
    plan.check("root_ok", real_dir, "the folder exists as a real directory in its canonical spelling" if real_dir
               else "the folder is missing, a symlink, or not in its canonical (long) spelling")
    reason = forbidden_reason(root, env) if real_dir else ""
    plan.check("not_forbidden", real_dir and not reason, "not a protected folder" if real_dir and not reason
               else reason or "not measured")
    tree, walk_error = None, ""
    if real_dir:
        names = {K.MANIFEST_NAME, K.README_NAME}
        try:
            tree = inventory.walk(root)
            leftovers = [n for n in tree.top_level() if n in names or K.ARCHIVE_INFIX in n or n.startswith(
                (K.ORIGINALS_PREFIX, K.RESTORE_PREFIX))]
            plan.check("no_pack_files", not leftovers, "no pack files in the folder" if not leftovers else
                       "pack files already in the folder: " + ", ".join(leftovers))
        except InventoryError as exc:
            walk_error = str(exc)
            plan.check("no_pack_files", False, walk_error)
    else:
        plan.check("no_pack_files", False, "not measured")
    _walk_checks(plan, tree, walk_error, env)
    kids = _children(conn, project) if real_dir else []
    plan.children = [{"id": c["id"], "name": c["display_name"], "root": c["root"], "archived": bool(c["archived_at"])}
                     for c in kids]
    live_kids = [c["name"] for c in plan.children if not c["archived"]]
    plan.check("children_archived", not live_kids, "every project inside is hidden too" if not live_kids else
               "these projects inside the folder are not hidden: " + ", ".join(live_kids))
    live = _live_sessions(conn, root, panes) if real_dir else {}
    listing_ok = plan.check("pane_listing", panes.ok, "the live pane listing answered" if panes.ok else
                            f"the live pane listing did not answer ({panes.reason})")
    plan.check("no_live_sessions", listing_ok and not live, "no live session under the folder" if not live else
               "stop these sessions first: " + ", ".join(f"{n} ({w})" for n, w in live.items()))
    reports = _git_checks(plan, root, accept_local_only) if real_dir and tree is not None else []
    probe = archive_io.probe_works() if os.access(root, os.W_OK) else "the folder is not writable"
    plan.check("tar_works", not probe, "tar can write and read zstd" if not probe else probe)
    _describe(plan, tree, reports, accept_local_only)
    return plan


def _describe(plan: PackPlan, tree: Tree | None, reports: Sequence[git_check.RepoReport], accepted: bool) -> None:
    entries = tree.entries if tree else []
    low, high = inventory.estimate_archive_bytes(entries)
    plan.sizes = {"logical_bytes": tree.logical_bytes if tree else None, "allocated_bytes": tree.allocated_bytes if tree
                  else None, "file_count": tree.file_count if tree else None, "estimate_low": low, "estimate_high": high}
    if tree:
        ranked = sorted(tree.top_sizes.items(), key=lambda kv: -kv[1])[:K.LARGEST_FOLDERS]
        plan.largest_folders = [{"name": n, "bytes": b} for n, b in ranked]
    plan.material = {
        "kind": "pack", "project": plan.project["id"], "root": plan.root, "identity": folder_identity(plan.root),
        "files": plan.sizes["file_count"], "bytes": plan.sizes["logical_bytes"],
        "signature": inventory.stat_signature(entries), "heads": sorted((r.path, r.head) for r in reports),
        "children": sorted(c["id"] for c in plan.children), "accept_local_only": bool(accepted),
        "local_only": plan.local_only,
    }
    plan.seal()


def folder_identity(path: str) -> Any:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_dev, st.st_ino]
