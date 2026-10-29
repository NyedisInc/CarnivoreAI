
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.cplugs.sdk import app_info

logger = structlog.get_logger()

SETTING = "sourceFolder"
REQUIRED = (
    ("web/package.json", "web/package.json is missing"),
    ("web/node_modules/.bin/vite", "web/node_modules is not installed (run npm ci in web/)"),
    ("web/vite.widget-draft.config.ts", "web/vite.widget-draft.config.ts is missing"),
    ("scripts/widgets/capture_one.py", "scripts/widgets/capture_one.py is missing"),
    ("src/data/widgets.json", "src/data/widgets.json is missing"),
    (".git", "it is not a git repository"),
)
MAIN_CHECKOUT = os.environ.get("CARNIVORE_REPO_ROOT") or str(
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Sync/Development/Org/Tooling/CloudeCode"
)
PREFERRED_BRANCH = "widget-lab-drafts"
NEVER_PICKED = frozenset({"joe-staging"})
PICK_TTL_S = 20.0
GIT_TIMEOUT_S = 5
VERSION_SHA = re.compile(r"(?:^|[.-])g([0-9a-f]{7,40})$")
NO_FOLDER_MESSAGE = "no widget lab source folder was found: set one in Settings, under the widget lab plugin (developer mode must be on)"

_setting: Optional[Callable[[], str]] = None
_picked: Optional[tuple] = None


def bind_setting(getter: Optional[Callable[[], str]]) -> None:
    global _setting
    _setting = getter
    forget_pick()


def forget_pick() -> None:
    global _picked
    _picked = None


def setting_value() -> str:
    if _setting is None:
        return ""
    try:
        value = _setting()
    except (RuntimeError, OSError, ValueError, TypeError):
        logger.warning("widget_lab_source_setting_unreadable")
        return ""
    return value.strip() if isinstance(value, str) else ""


def problems(root: Path) -> List[str]:
    if not root.is_dir():
        return ["it is not a folder"]
    return [reason for rel, reason in REQUIRED if not (root / rel).exists()]


def own_tree() -> Optional[Path]:
    from src.cplugs.devwidgetlab.drafts import store  # noqa: PLC0415

    return store.REPO if store.SCRIPT.is_file() and (store.REPO / "web" / "package.json").is_file() else None


def never_picked(root: Path) -> bool:
    return root.name in NEVER_PICKED


def _git(root: Path, *args: str) -> str:
    if not app_info.git_available():
        return ""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def worktrees(main: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in _git(main, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            rows.append({"path": line[len("worktree "):], "branch": "", "head": ""})
        elif line.startswith("HEAD ") and rows:
            rows[-1]["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch ") and rows:
            rows[-1]["branch"] = line[len("branch "):].removeprefix("refs/heads/")
    return rows


def app_sha() -> str:
    own = own_tree()
    if own is not None:
        head = _git(own, "rev-parse", "HEAD").strip()
        if head:
            return head
    match = VERSION_SHA.search(app_info.app_version().strip())
    return match.group(1) if match else ""


def same_commit(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def main_checkout() -> Path:
    own = own_tree()
    if own is not None:
        common = _git(own, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        if common:
            return Path(common).parent
    return Path(MAIN_CHECKOUT)


def _candidates(main: Path) -> List[Path]:
    rows = worktrees(main)
    own = own_tree()
    running = _git(own, "rev-parse", "--abbrev-ref", "HEAD").strip() if own is not None else ""
    sha = app_sha()
    same = {Path(row["path"]) for row in rows if same_commit(row["head"], sha)}
    rest = [row for row in rows if Path(row["path"]) != main]
    ordered = sorted(rest, key=lambda row: 0 if running and row["branch"] == running else 1 if row["branch"] == PREFERRED_BRANCH else 2)
    return sorted([main, *(Path(row["path"]) for row in ordered)], key=lambda path: 0 if path in same else 1)


def auto_pick() -> Optional[Path]:
    global _picked
    if _picked is not None and time.monotonic() - _picked[0] < PICK_TTL_S:
        return _picked[1]
    found = next((root for root in _candidates(main_checkout()) if not never_picked(root) and not problems(root)), None)
    _picked = (time.monotonic(), found)
    return found


def own_usable() -> Optional[Path]:
    own = own_tree()
    return own if own is not None and not never_picked(own) else None


def configured_root() -> Optional[Path]:
    saved = setting_value()
    if not saved or not app_info.developer_mode_on():
        return None
    root = Path(saved).expanduser()
    return root if root.is_absolute() and not problems(root) else None


def resolve(storage_path: Optional[Path] = None) -> Optional[Path]:
    if app_info.developer_mode_on():
        return configured_root() or own_usable() or auto_pick()
    return own_usable()


def status(storage_path: Optional[Path] = None) -> Dict[str, Any]:
    saved = setting_value()
    chosen = configured_root()
    root = resolve(storage_path)
    origin = "none" if root is None else "setting" if root == chosen else "own_tree" if root == own_usable() else "auto"
    broken = problems(Path(saved).expanduser()) if saved and chosen is None and app_info.developer_mode_on() else []
    if saved and not Path(saved).expanduser().is_absolute():
        broken = ["it is not an absolute path"]
    return {"root": str(root) if root else "", "origin": origin, "setting": saved, "problems": broken}
