
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.core.claude_project_dirs import path_spellings
from src.core.claude_rename_retry_store import ledger_path as rename_ledger_path
from src.core.inventory.locations import Locations
from src.core.inventory.model import KIND_ENTRY, REPORT, ROLE_KEY, ROLE_PATH, Artifact, FieldRef, ProjectIdentity, SessionIdentity

logger = structlog.get_logger()

UNREAD_STORE = "unread_state.json"
CONFIG_STORE = "config.json"
RENAME_STORE = "rename-retry/marks.json"
CLAUDE_JSON_STORE = ".claude.json"
ACCOUNT_PINS_KEY = "session_account_pins"
CLAUDE_JSON = ".claude.json"
CLAUDE_PROJECTS_KEY = "projects"


def _read_object(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("inventory_json_unreadable", path=str(path), error=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


def _unread_keys(ident: SessionIdentity) -> List[str]:
    keys = [f"row:{ident.row_id}"]
    if ident.tmux_name and ident.tmux_epoch is not None:
        keys.append(f"{ident.tmux_name}@{ident.tmux_epoch}")
    if ident.tmux_name:
        keys.append(ident.tmux_name)
    return keys


def _rename_marks(ident: SessionIdentity, locations: Locations) -> List[Artifact]:
    path = rename_ledger_path(Path(locations.state_dir))
    data = _read_object(path)
    marks = data.get("marks") if data else None
    if not isinstance(marks, dict):
        return []
    keys = [k for k in marks if k.rpartition(":")[2] == str(ident.row_id)]
    if not keys:
        return []
    return [Artifact(store=RENAME_STORE, kind=KIND_ENTRY, what=f"marks[{len(keys)} key(s)]", count=len(keys), action=REPORT,
                     reason="the title sync's retry budget for this session; rebuilt on the next rename",
                     locator={"file": str(path), "key": "marks", "match": keys}, derived=True,
                     rewrite=[FieldRef("marks key: <conversation uuid or none>:<sessions.id>", ROLE_KEY)])]


def session_entries(ident: SessionIdentity, locations: Locations) -> List[Artifact]:
    out: List[Artifact] = _rename_marks(ident, locations)
    unread_path = locations.unread_state()
    unread = _read_object(unread_path)
    for key in _unread_keys(ident) if unread else []:
        if key in unread:
            reason = ("keyed by tmux name alone (the legacy shape), which a later session may reuse" if key == ident.tmux_name
                      else "the unread flag of this session instance")
            out.append(Artifact(store=UNREAD_STORE, kind=KIND_ENTRY, what=key, count=1, action=REPORT, reason=reason,
                                locator={"file": str(unread_path), "key": key},
                                rewrite=[FieldRef("key: row:<sessions.id> | <tmux name>@<epoch> | <tmux name>", ROLE_KEY)]))
    config = _read_object(locations.config_path)
    pins = config.get(ACCOUNT_PINS_KEY) if config else None
    if isinstance(pins, dict) and ident.session_uuid in pins:
        out.append(Artifact(store=CONFIG_STORE, kind=KIND_ENTRY, what=f"{ACCOUNT_PINS_KEY}[{ident.session_uuid}]", count=1,
                            action=REPORT, reason="the account this session is pinned to; the account id is this install's",
                            locator={"file": str(locations.config_path), "key": f"{ACCOUNT_PINS_KEY}.{ident.session_uuid}"},
                            rewrite=[FieldRef("session_uuid", ROLE_KEY)]))
    return out


def claude_json_files(locations: Locations) -> List[Path]:
    candidates: List[Path] = []
    for home in locations.claude_homes():
        candidates.append(Path(home) / CLAUDE_JSON)
        if Path(home) == Path.home() / ".claude":
            candidates.append(Path.home() / CLAUDE_JSON)
    seen: set = set()
    out: List[Path] = []
    for path in candidates:
        if path.is_file() and str(path.resolve()) not in seen:
            seen.add(str(path.resolve()))
            out.append(path)
    return out


def project_entries(project: ProjectIdentity, locations: Locations) -> List[Artifact]:
    out: List[Artifact] = []
    spellings = list(dict.fromkeys(path_spellings(project.root) or [project.root]))
    for path in claude_json_files(locations):
        data = _read_object(path)
        projects = data.get(CLAUDE_PROJECTS_KEY) if data else None
        if not isinstance(projects, dict):
            continue
        for spelling in spellings:
            if spelling in projects:
                out.append(Artifact(store=CLAUDE_JSON_STORE, kind=KIND_ENTRY, what=f"{path}#projects[{spelling}]", count=1,
                                    action=REPORT, reason="Claude Code's own trust, permission and MCP settings for the folder; "
                                    "no Carnivore code ever edits this file, an import only offers to carry the entry",
                                    locator={"file": str(path), "key": f"{CLAUDE_PROJECTS_KEY}.{spelling}"},
                                    rewrite=[FieldRef(f"{CLAUDE_PROJECTS_KEY} key: the project's absolute path", ROLE_PATH)]))
    return out


_FOLD_LISTS = (("collapsed",), ("mobile", "collapsed"))


def _folds(arrangement: Dict[str, Any], wanted: List[str]) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for route in _FOLD_LISTS:
        node: Any = arrangement
        for step in route:
            node = node.get(step) if isinstance(node, dict) else None
        if isinstance(node, list):
            hit = [key for key in wanted if key in node]
            if hit:
                found[".".join(route)] = hit
    return found


def project_preference_entries(project: ProjectIdentity, locations: Locations) -> List[Artifact]:
    from src.core import ui_preferences

    config = _read_object(locations.config_path)
    if config is None:
        return []
    arrangement = (ui_preferences.read_block(config).get("values") or {}).get("drawer_arrangement")
    if not isinstance(arrangement, dict):
        return []
    wanted = [f"p:{project.project_id}"] + ([f"c:{project.company_id}"] if project.company_id is not None else [])
    out: List[Artifact] = []
    for route, keys in _folds(arrangement, wanted).items():
        for key in keys:
            own = key.startswith("p:")
            out.append(Artifact(store="ui_preferences", kind=KIND_ENTRY, what=f"drawer_arrangement.{route}[{key}]", count=1,
                                action=REPORT, reason=("the project's fold in the drawer" if own else
                                                       "the company's fold in the drawer, shared with its sibling projects"),
                                locator={"file": str(locations.config_path), "key": f"ui_preferences.values.drawer_arrangement.{route}", "match": key},
                                rewrite=[FieldRef("fold key: p:<projects.id> | c:<companies.id>", ROLE_KEY)]))
    return out
