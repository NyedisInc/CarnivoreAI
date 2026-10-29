
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from pydantic import ValidationError

from src.core import ui_preferences
from src.core.widget_fits.rules import (
    WIDGETS_PATH,
    Fit,
    load_fits,
    placements,
    widget_for_slot,
)

BOARD_FORMAT = "carnivore-board"
BOARD_VERSION = 1
MAX_BOARD_FILE_BYTES = 65536
MAX_SETTINGS_ENTRIES = 64
_TOP_KEYS = frozenset({"format", "version", "exported_at", "board", "drawer_zone", "settings"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class BoardFileError(ValueError):
    pass


@dataclass
class ImportPlan:

    name: str
    layout: Dict[str, Any]
    drawer_zone: Optional[Dict[str, Any]]
    settings: Dict[str, Dict[str, Any]]
    widgets: List[str] = field(default_factory=list)
    refusals: List[str] = field(default_factory=list)

    def preview(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "widgets": self.widgets,
            "settings": sorted(self.settings),
            "drawer_zone": [item["widget"] for item in (self.drawer_zone or {}).get("items", [])],
            "refusals": self.refusals,
            "ok": not self.refusals,
        }


def _replaced_ids(path=WIDGETS_PATH) -> frozenset:
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    replaced = document.get("replaced") if isinstance(document, dict) else None
    return frozenset(replaced) if isinstance(replaced, dict) else frozenset()


def _board_of(values: Mapping[str, Any], board_id: str) -> Mapping[str, Any]:
    home = values.get("home_layout") if isinstance(values, Mapping) else None
    boards = home.get("boards") if isinstance(home, Mapping) else None
    for board in boards if isinstance(boards, list) else []:
        if isinstance(board, Mapping) and board.get("id") == board_id:
            return board
    raise BoardFileError(f"there is no board '{board_id}'")


def build_export(
    values: Mapping[str, Any],
    board_id: str,
    widget_settings: Mapping[str, Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    board = _board_of(values, board_id)
    layout = board.get("layout")
    placed = [widget_for_slot(slot) for slot in placements(layout)]
    zone = values.get("drawer_zone")
    in_zone = [item.get("widget") for item in zone.get("items", [])] if isinstance(zone, Mapping) else []
    settings = {
        widget: dict(node["values"])
        for widget, node in widget_settings.items()
        if widget in placed + in_zone and isinstance(node, Mapping) and isinstance(node.get("values"), Mapping) and node["values"]
    }
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    document: Dict[str, Any] = {
        "format": BOARD_FORMAT,
        "version": BOARD_VERSION,
        "exported_at": stamp,
        "board": {"name": board.get("name"), "layout": layout},
        "settings": settings,
    }
    if isinstance(zone, Mapping):
        document["drawer_zone"] = dict(zone)
    return document


def _parse(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, (bytes, str)):
        size = len(raw.encode("utf-8") if isinstance(raw, str) else raw)
        if size > MAX_BOARD_FILE_BYTES:
            raise BoardFileError(f"a board file is at most {MAX_BOARD_FILE_BYTES // 1024} KiB")
        try:
            raw = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BoardFileError("the file is not JSON") from exc
    elif len(json.dumps(raw, default=str).encode("utf-8")) > MAX_BOARD_FILE_BYTES:
        raise BoardFileError(f"a board file is at most {MAX_BOARD_FILE_BYTES // 1024} KiB")
    if not isinstance(raw, dict) or raw.get("format") != BOARD_FORMAT:
        raise BoardFileError("this is not a carnivore board file")
    if raw.get("version") != BOARD_VERSION:
        raise BoardFileError(f"board file version {raw.get('version')!r} is not one this install reads (it reads {BOARD_VERSION})")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise BoardFileError(f"unknown field '{unknown[0][:40]}' in the board file")
    return raw


def _settings_refusals(settings: Any) -> List[str]:
    if settings is None:
        return []
    if not isinstance(settings, dict) or len(settings) > MAX_SETTINGS_ENTRIES:
        return [f"settings must be an object of at most {MAX_SETTINGS_ENTRIES} widgets"]
    out = []
    for widget, entry in settings.items():
        if not _ID_RE.match(str(widget)) or not isinstance(entry, dict):
            out.append(f"settings for '{str(widget)[:40]}' are not a widget id and an object")
        elif any(ui_preferences.is_secret_name(str(key)) for key in entry):
            out.append(f"settings for {widget} name a secret, which a board file never carries")
    return out


def plan_import(raw: Any, fits: Optional[Mapping[str, Fit]] = None) -> ImportPlan:
    document = _parse(raw)
    contract = fits if fits is not None else load_fits()
    replaced = _replaced_ids()
    refusals: List[str] = []
    board = document.get("board")
    if not isinstance(board, dict):
        raise BoardFileError("the board file carries no board")
    try:
        checked = ui_preferences.HomeBoard(id="import", name=board.get("name") or "imported", layout=board.get("layout"))
    except ValidationError as exc:
        raise BoardFileError(f"the board is not a layout this install reads: {exc.errors()[0].get('msg', 'invalid')}") from exc
    widgets: List[str] = []
    for slot in placements(checked.layout):
        widget = widget_for_slot(slot)
        widgets.append(widget)
        if widget not in contract and widget not in replaced:
            refusals.append(f"{widget} is not a widget this install has")
    zone = document.get("drawer_zone")
    drawer: Optional[Dict[str, Any]] = None
    if zone is not None:
        try:
            drawer = ui_preferences.DrawerZone.model_validate(zone).model_dump()
        except ValidationError as exc:
            refusals.append(f"the drawer area is not one this install reads: {exc.errors()[0].get('msg', 'invalid')}")
    settings = document.get("settings")
    refusals.extend(_settings_refusals(settings))
    return ImportPlan(
        name=checked.name,
        layout=checked.layout,
        drawer_zone=drawer,
        settings=dict(settings) if isinstance(settings, dict) and not _settings_refusals(settings) else {},
        widgets=widgets,
        refusals=refusals,
    )


def fresh_board_id(existing: List[str]) -> str:
    while True:
        candidate = f"b{secrets.token_hex(4)}"
        if candidate not in existing:
            return candidate
