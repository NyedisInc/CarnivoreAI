
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.cplugs.devwidgetlab.drafts import store
from src.cplugs.devwidgetlab.errors import DraftInvalid
from src.cplugs.sdk import app_info

logger = structlog.get_logger()

NO_GIT = "git is not installed on this computer (no developer tools)"
WIDGETS_JSON = "src/data/widgets.json"
CONTRACTS_JSON = "src/data/widget-contracts.json"

WIRING = (
    "web/src/opscenter/engine/meta.ts: add the `{slot}` record to META from widget.json `cell` (and the CellId type); its title string to client/js/i18n/catalog.en.js",
    "web/src/opscenter/cells/registry.ts: import the cell and add `{slot}` to REGISTRY",
    "web/src/opscenter/widgets/core-manifests.ts: add `{slot}` to EXTRAS (category, type, capabilities from widget.json)",
    "web/src/opscenter/widgets/fixtures/index.ts: import `{export_name}` and add `core.{slot}` to TABLES",
    "run the Widget Lab matrix for the new widget, then `scripts/features.py check`",
)


def _changed_since(repo: Path, base: str, rel: str) -> bool:
    if not base or not app_info.git_available():
        return False
    try:
        done = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", base, "HEAD", "--", rel], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 1


def _records(repo: Path, rel: str) -> List[Dict[str, Any]]:
    try:
        return list(json.loads((repo / rel).read_text(encoding="utf-8"))["widgets"])
    except (OSError, ValueError, KeyError) as exc:
        raise DraftInvalid(f"{rel} is unreadable: {type(exc).__name__}") from exc


def plan(folder: Path, repo: Path) -> Dict[str, Any]:
    record = store.read_record(folder)
    problems: List[str] = []
    warnings: List[str] = []
    if not app_info.git_available():
        problems.append(NO_GIT)
    copies = []
    for rel in store.mirrored_files(folder):
        try:
            store.mirror_target(rel)
        except DraftInvalid as exc:
            problems.append(str(exc))
            continue
        exists = (repo / rel).is_file()
        changed = exists and _changed_since(repo, record.get("base_sha") or "", rel)
        if changed:
            warnings.append(f"{rel} changed on the checkout since this draft began; merge by hand before shipping")
        copies.append({"path": rel, "action": "overrides" if exists else "adds", "repo_changed": changed})
    if record["kind"] == "revision" and not copies:
        problems.append("a revision with no changed file has nothing to ship")
    appends: List[Dict[str, Any]] = []
    wiring: List[str] = []
    if record["kind"] == "new":
        widget = _read(folder / "widget.json", problems)
        for name, file in (("widget.json", WIDGETS_JSON), ("contract.json", CONTRACTS_JSON)):
            if _read(folder / name, problems) is None:
                continue
            present = any(r.get("id") == record["widget"] for r in _records(repo, file))
            appends.append({"file": file, "id": record["widget"], "present": present})
            if present:
                problems.append(f"{record['widget']} is already in {file}")
        if widget:
            wiring = [line.format(slot=widget["slot"], export_name=widget["fixtures_export"]) for line in WIRING]
    return {"slug": record["slug"], "kind": record["kind"], "widget": record["widget"], "copy": copies, "appends": appends, "wiring": wiring,
            "problems": problems, "warnings": warnings}


def _read(path: Path, problems: List[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        problems.append(f"{path.name} is missing or unreadable")
        return None


def _append(repo: Path, rel: str, record: Dict[str, Any]) -> None:
    path = repo / rel
    document = json.loads(path.read_text(encoding="utf-8"))
    document["widgets"].append(record)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def trash_folder(folder: Path, trash: Path) -> str:
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"widget-draft-{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(folder), str(target))
    return str(target)


def apply(folder: Path, repo: Path, trash: Path, keep: bool = False) -> Dict[str, Any]:
    shipped = plan(folder, repo)
    if shipped["problems"]:
        raise DraftInvalid("; ".join(shipped["problems"]))
    for item in shipped["copy"]:
        target = repo / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / store.MIRROR_FOLDER / item["path"], target)
    if shipped["kind"] == "new":
        widget = json.loads((folder / "widget.json").read_text(encoding="utf-8"))
        _append(repo, WIDGETS_JSON, {"id": widget["id"], "instancing": widget["instancing"], "fits": widget["fits"],
                                     **({"settings": widget["settings"]} if widget.get("settings") else {})})
        _append(repo, CONTRACTS_JSON, json.loads((folder / "contract.json").read_text(encoding="utf-8")))
    trashed = "" if keep else trash_folder(folder, trash)
    logger.info("widget_lab_draft_shipped", slug=shipped["slug"], files=len(shipped["copy"]), trashed=trashed)
    return {**shipped, "trashed": trashed}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    if not app_info.git_available():
        raise DraftInvalid(NO_GIT)
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DraftInvalid(f"git could not run: {type(exc).__name__}") from exc


def worktree_parent(repo: Path) -> Path:
    return Path.home() / "dev-worktrees" / repo.name.lower()


def apply_isolated(folder: Path, repo: Path, trash: Path, worktrees: Path, keep: bool = False) -> Dict[str, Any]:
    shipped = plan(folder, repo)
    if shipped["problems"]:
        raise DraftInvalid("; ".join(shipped["problems"]))
    branch = f"widget-draft/{folder.name}"
    target = worktrees.resolve() / f"widget-draft-{folder.name}"
    if target.is_relative_to(repo.resolve()) or target.exists():
        raise DraftInvalid(f"the worktree path {target} is inside the checkout or already exists")
    made = _git(repo, "worktree", "add", "-b", branch, str(target), "HEAD")
    if made.returncode != 0:
        raise DraftInvalid(f"git worktree add refused: {made.stderr.strip()[:300]}")
    applied = apply(folder, target, trash, keep=True)
    paths = [item["path"] for item in applied["copy"]] + ([WIDGETS_JSON, CONTRACTS_JSON] if applied["kind"] == "new" else [])
    committed = _git(target, "add", "--", *paths).returncode == 0 and _git(target, "commit", "-m", f"widget draft {folder.name}: ship the draft's files", "--", *paths).returncode == 0
    sha = _git(target, "rev-parse", "HEAD").stdout.strip() if committed else ""
    if not committed:
        logger.warning("widget_lab_ship_commit_failed", slug=folder.name, worktree=str(target))
    trashed = "" if keep else trash_folder(folder, trash)
    return {**applied, "trashed": trashed, "worktree": str(target), "branch": branch, "committed": committed, "sha": sha}
