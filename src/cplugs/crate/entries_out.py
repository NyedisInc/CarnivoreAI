
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.cplugs.crate import constants as K
from src.cplugs.crate.forbidden import SourceForbidden, deny_inodes, open_source
from src.cplugs.sdk import crate_sources as cs

_PREF_PREFIX = "ui_preferences.values."
_LAYOUTS = "terminal_layouts.sessions."
_ARRANGEMENT = "drawer_arrangement"


@dataclass
class ScopeKeys:

    session_uuids: Set[str] = field(default_factory=set)
    row_ids: Set[int] = field(default_factory=set)
    project_ids: Set[int] = field(default_factory=set)
    company_ids: Set[int] = field(default_factory=set)

    def needles(self) -> Set[str]:
        return (set(self.session_uuids) | {f"terminal:row:{r}" for r in self.row_ids}
                | {f"p:{p}" for p in self.project_ids} | {f"c:{c}" for c in self.company_ids})


class EntryUnreadable(Exception):
    pass


def _load(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise EntryUnreadable(f"{path} could not be read ({type(exc).__name__})") from exc


def _walk(value: Any, steps: Sequence[str]) -> Any:
    for step in steps:
        value = value.get(step) if isinstance(value, dict) else None
    return value


def slice_matching(value: Any, needles: Set[str], path: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    here = list(path or [])
    out: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            if key in needles:
                out.append({"path": here + [key], "value": value[key]})
            else:
                out += slice_matching(value[key], needles, here + [key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str) and item in needles:
                out.append({"path": here + [index], "value": item})
            elif isinstance(item, (dict, list)):
                out += slice_matching(item, needles, here + [index])
    return out


def _preference(art: cs.Artifact, keys: ScopeKeys) -> Dict[str, Any]:
    key = str(art.locator.get("key", ""))
    if not key.startswith(_PREF_PREFIX):
        raise ValueError(f"no handler for ui_preferences key {key}")
    values = _walk(_load(str(art.locator["file"])), ["ui_preferences", "values"])
    rest = key[len(_PREF_PREFIX):]
    if rest.startswith(_LAYOUTS):
        sessions, name = _walk(values, ["terminal_layouts", "sessions"]), rest[len(_LAYOUTS):]
        if not isinstance(sessions, dict) or name not in sessions:
            raise EntryUnreadable(f"ui_preferences no longer holds the grid {name}")
        return {"value": sessions[name]}
    if rest == _ARRANGEMENT and "match" not in art.locator:
        return {"slice": slice_matching(_walk(values, [_ARRANGEMENT]), keys.needles())}
    if rest.startswith(_ARRANGEMENT + ".") and "match" in art.locator:
        member = _walk(values, rest.split("."))
        match = art.locator["match"]
        wanted = set(match) if isinstance(match, list) else {match}
        return {"slice": slice_matching(member, wanted)}
    raise ValueError(f"no handler for ui_preferences key {key}")


def _claude_json(art: cs.Artifact, locs: cs.Locations) -> Dict[str, Any]:
    file = str(art.locator["file"])
    key = str(art.locator["key"])
    spelling = key[len("projects."):] if key.startswith("projects.") else None
    if spelling is None:
        raise ValueError(f"no handler for .claude.json key {key}")
    trust = cs.load_trust_map(Path(file))
    if trust is None:
        raise EntryUnreadable(f"{file} could not be read for folder trust")
    files = [os.path.realpath(str(p)) for p in cs.claude_json_files(locs)]
    index = files.index(os.path.realpath(file)) if os.path.realpath(file) in files else 0
    return {"value": {"trusted": bool(trust.get(spelling, False))}, "file_index": index}


def _theme(art: cs.Artifact, locs: cs.Locations) -> Dict[str, Any]:
    """A folder's ``.cc.theme`` as text, refused over 4 KiB. Blocking. Raises EntryUnreadable.

    Opened through ``forbidden.open_source`` (``O_NOFOLLOW``, a regular file, not a credential file's inode), so a
    ``.cc.theme`` that is a symlink or a hard link to a credential file is a blocker sentence and is never read.
    """
    path = str(art.locator.get("path") or art.what)
    try:
        fd, _st = open_source(path, [os.path.realpath(os.path.dirname(path))], deny_inodes(locs))
    except SourceForbidden as exc:
        raise EntryUnreadable(f"{path} is not read: {exc.detail}") from exc
    except OSError as exc:
        raise EntryUnreadable(f"{path} could not be read as text ({type(exc).__name__})") from exc
    try:
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(K.THEME_DOTFILE_MAX_BYTES + 1)
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EntryUnreadable(f"{path} could not be read as text ({type(exc).__name__})") from exc
    if len(data) > K.THEME_DOTFILE_MAX_BYTES:
        raise EntryUnreadable(f"{path} is larger than {K.THEME_DOTFILE_MAX_BYTES} bytes; a theme name is never that long")
    return {"key": "text", "value": {"path": path, "text": text}}


def _one(art: cs.Artifact, keys: ScopeKeys, locs: cs.Locations) -> Dict[str, Any]:
    store = art.store
    if store == cs.STORE_THEME_DOTFILE:
        return _theme(art, locs)
    key = str(art.locator.get("key", ""))
    if store in (cs.UNREAD_STORE, cs.PINNED_THEMES_FILE):
        data = _load(str(art.locator["file"]))
        if not isinstance(data, dict) or key not in data:
            raise EntryUnreadable(f"{store} no longer holds {key}")
        return {"value": data[key]}
    if store == cs.CONFIG_STORE:
        head, _, member = key.partition(".")
        block = _walk(_load(str(art.locator["file"])), [head])
        if not isinstance(block, dict) or member not in block:
            raise EntryUnreadable(f"config.json no longer holds {key}")
        return {"value": block[member]}
    if store == cs.CLAUDE_JSON_STORE:
        return _claude_json(art, locs)
    if store == cs.PREFERENCES:
        return _preference(art, keys)
    if store == cs.JOURNAL:
        found = cs.journal_entries(Path(locs.state_dir), keys.session_uuids, keys.row_ids)
        if found is None:
            raise EntryUnreadable("the reboot journal could not be read")
        return {"value": found}
    raise ValueError(f"no crate policy for entry store {store}")


def read_entries(arts: Sequence[cs.Artifact], keys: ScopeKeys, locs: cs.Locations) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    blockers: List[str] = []
    seen: Set[Tuple[str, str, str]] = set()
    for art in arts:
        file = str(art.locator.get("file") or art.locator.get("path") or art.what)
        ident = (art.store, file, json.dumps([art.locator.get("key"), art.locator.get("match")], default=str))
        if ident in seen:
            continue
        seen.add(ident)
        try:
            fields = _one(art, keys, locs)
        except (EntryUnreadable, ValueError) as exc:
            blockers.append(str(exc))
            continue
        record: Dict[str, Any] = {"store": art.store, "file_label": os.path.basename(file), "file_index": 0,
                                  "key": str(art.locator.get("key", ""))}
        if "match" in art.locator:
            record["match"] = art.locator["match"]
        record.update(fields)
        records.append(record)
    records.sort(key=lambda r: (r["store"], r["key"], r["file_index"], json.dumps(r.get("match"), default=str)))
    return records, blockers
