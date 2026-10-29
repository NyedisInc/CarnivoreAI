
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core import config_writer, ui_preferences
from src.core.account_switch import session_pin
from src.core.crate_format.constants import M_ENTRIES
from src.core.crate_format.reader import CrateReader
from src.core.crate_import import idmap as ids_keys
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import W_ENTRY_NOT_RESTORED, Collector
from src.core.inventory.model import MAIN_STORE
from src.core.project_move.paths import PathMapping
from src.core.sessions import theme_dotfile

logger = structlog.get_logger()

PREFERENCES = "ui_preferences"
ARRANGEMENT = "drawer_arrangement"
LAYOUTS = "terminal_layouts"
ACCOUNT_PINS = "config.json"
THEME_STORE = "cc-theme"
COMPANIES = f"{MAIN_STORE}.companies"
PROJECTS = f"{MAIN_STORE}.projects"
SESSIONS = f"{MAIN_STORE}.sessions"
NEVER: Dict[str, str] = {
    "pinned_themes.json": "keyed_by_tmux_name", "unread_state.json": "transient", "rename-retry/marks.json": "transient",
    ".claude.json": "never_written", "session-journal": "handled_by_journal_step"}
_THEME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PIN_PREFIX = "session_account_pins."
_ARRANGEMENT_KEY = f"ui_preferences.values.{ARRANGEMENT}"
_LAYOUT_KEY = f"ui_preferences.values.{LAYOUTS}"
UNDO_DRAWER, UNDO_PIN, UNDO_THEME = "drawer", "pin", "theme"


def records(reader: CrateReader) -> List[Dict[str, Any]]:
    if not reader.has(M_ENTRIES):
        return []
    found = reader.read_json(M_ENTRIES)
    return [e for e in (found.get("entries") if isinstance(found, dict) else []) or [] if isinstance(e, dict)]


def summarize(reader: CrateReader) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for entry in records(reader):
        out[str(entry.get("store"))] = out.get(str(entry.get("store")), 0) + 1
    return out


def remap_token(token: Any, idmap: IdMap) -> Optional[Any]:
    if not isinstance(token, str):
        return token
    for prefix, table in (("terminal:row:", SESSIONS), ("row:", SESSIONS), ("p:", PROJECTS), ("c:", COMPANIES)):
        if token.startswith(prefix) and token[len(prefix):].isdigit():
            mapped = idmap.get(table, int(token[len(prefix):]))
            return f"{prefix}{mapped}" if mapped is not None else None
    mapped_uuid = idmap.get(ids_keys.SESSION_UUIDS, token)
    return str(mapped_uuid) if mapped_uuid is not None else token


def _add_member(root: Dict[str, Any], path: List[Any], value: Any, idmap: IdMap, added: Optional[List[Dict[str, Any]]] = None) -> bool:
    if not path or any(isinstance(step, int) for step in path[:-1]):
        return False
    value = remap_token(value, idmap) if isinstance(value, str) else value
    if value is None:
        return False
    steps = [remap_token(s, idmap) if isinstance(s, str) else s for s in path]
    if any(s is None for s in steps):
        return False
    node: Any = root
    for step, following in zip(steps[:-1], steps[1:]):
        child = node.get(step) if isinstance(node, dict) else None
        if child is None and isinstance(node, dict):
            child = node[step] = [] if isinstance(following, int) else {}
        if not isinstance(child, (dict, list)) or (isinstance(following, int) != isinstance(child, list)):
            return False
        node = child
    last = steps[-1]
    if isinstance(last, int) and isinstance(node, list):
        if value in node:
            return False
        node.append(value)
        if added is not None:
            added.append({"path": steps, "value": value})
        return True
    if isinstance(last, str) and isinstance(node, dict) and last not in node:
        node[last] = value
        if added is not None:
            added.append({"path": steps, "value": value})
        return True
    return False


def merge_arrangement(stored: Optional[Dict[str, Any]], entries: List[Dict[str, Any]], idmap: IdMap,
                      added_out: Optional[List[Dict[str, Any]]] = None) -> Tuple[Dict[str, Any], int]:
    merged = copy.deepcopy(stored) if isinstance(stored, dict) else {"v": 1}
    added = 0
    for entry in entries:
        base = [part for part in str(entry.get("key", ""))[len(_ARRANGEMENT_KEY):].split(".") if part]
        for member in entry.get("slice") or []:
            if isinstance(member, dict) and isinstance(member.get("path"), list):
                if _add_member(merged, [*base, *member["path"]], member.get("value"), idmap, added_out):
                    added += 1
    return merged, added


def _write_preferences(config_path: Path, entries: List[Dict[str, Any]], idmap: IdMap, col: Collector,
                       undo: Optional[List[Dict[str, Any]]] = None) -> int:
    added: Dict[str, Any] = {"n": 0, "members": []}

    def mutate(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        stored = ui_preferences.read_block(config)["values"].get(ARRANGEMENT)
        added["members"] = []
        merged, count = merge_arrangement(stored, entries, idmap, added["members"])
        if count == 0:
            return None
        changes = ui_preferences.validate_changes({ARRANGEMENT: merged})
        new_config, _block, moved = ui_preferences.apply_changes(config, changes)
        added["n"] = count if moved else 0
        return new_config if moved else None

    try:
        config_writer.commit(config_path, mutate)
    except (FileNotFoundError, ValueError, OSError) as exc:
        col.warn(W_ENTRY_NOT_RESTORED, f"{PREFERENCES}: {type(exc).__name__}")
        return 0
    if undo is not None and added["n"]:
        undo.append({"kind": UNDO_DRAWER, "members": added["members"]})
    return added["n"]


def _pins(config_path: Path, entries: List[Dict[str, Any]], idmap: IdMap, own: bool, col: Collector,
          undo: Optional[List[Dict[str, Any]]] = None) -> int:
    written = 0
    for entry in entries:
        key = str(entry.get("key", ""))
        if not key.startswith(_PIN_PREFIX) or not isinstance(entry.get("value"), str):
            continue
        uuid = key[len(_PIN_PREFIX):]
        if not own:
            col.warn(W_ENTRY_NOT_RESTORED, f"account pin of {uuid}: foreign crate")
            continue
        local = str(idmap.get(ids_keys.SESSION_UUIDS, uuid) or uuid)
        if session_pin.carry(config_path, local, entry["value"]):
            written += 1
            if undo is not None:
                undo.append({"kind": UNDO_PIN, "uuid": local, "account": entry["value"]})
    return written


def _themes(entries: List[Dict[str, Any]], mapping: PathMapping, col: Collector, installed: Optional[Callable[[str], bool]],
            undo: Optional[List[Dict[str, Any]]] = None) -> int:
    written = 0
    for entry in entries:
        value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
        old_path, text = str(value.get("path") or ""), str(value.get("text") or "").strip()
        folder = mapping.apply(str(Path(old_path).parent)) if old_path else None
        if folder is None or not _THEME_ID.match(text) or (installed is not None and not installed(text)):
            col.warn(W_ENTRY_NOT_RESTORED, f"{theme_dotfile.DOTFILE_NAME}: {old_path or 'no path'}")
            continue
        if not Path(folder).is_dir() or theme_dotfile.read_project_theme(folder) is not None:
            continue
        theme_dotfile.write_project_theme(folder, text)
        written += 1
        if undo is not None:
            undo.append({"kind": UNDO_THEME, "folder": str(folder), "text": text})
    return written


def apply_entries(reader: CrateReader, config_path: Optional[Path], idmap: IdMap, mapping: PathMapping, *, own: bool, col: Collector,
                  theme_installed: Optional[Callable[[str], bool]] = None, undo: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    found = records(reader)
    out: Dict[str, Any] = {"drawer_members": 0, "pins": 0, "themes": 0, "not_restored": []}
    arrangement = [e for e in found if e.get("store") == PREFERENCES and str(e.get("key", "")).startswith(_ARRANGEMENT_KEY)]
    pins = [e for e in found if e.get("store") == ACCOUNT_PINS and str(e.get("key", "")).startswith(_PIN_PREFIX)]
    if config_path is None and (arrangement or pins):
        col.warn(W_ENTRY_NOT_RESTORED, "config.json: this install did not say where it is")
    elif config_path is not None:
        out["drawer_members"] = _write_preferences(config_path, arrangement, idmap, col, undo) if arrangement else 0
        out["pins"] = _pins(config_path, pins, idmap, own, col, undo)
    out["themes"] = _themes([e for e in found if e.get("store") == THEME_STORE], mapping, col, theme_installed, undo)
    reasons: Dict[str, str] = {}
    for entry in found:
        store, key = str(entry.get("store")), str(entry.get("key", ""))
        if store in NEVER:
            reasons[f"entry:{store}"] = NEVER[store]
        elif store == PREFERENCES and key.startswith(_LAYOUT_KEY):
            reasons[f"entry:{LAYOUTS}"] = "keyed_by_tmux_name"
    out["not_restored"] = [{"what": what, "why": why} for what, why in sorted(reasons.items())]
    return out
