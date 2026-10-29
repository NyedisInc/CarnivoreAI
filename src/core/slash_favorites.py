"""User-chosen favorites for the slash-command chip row.

``common_slash_commands`` used to be a HAND-PICKED list: whoever edited
config.json decided which commands got a chip, and a user who wanted a
different set had to hand-edit JSON. This module turns the same key into
the storage behind a STAR the user toggles on any command in the palette.
Same key, same two entry forms, same migration chain. What changes is who
writes it.

THE STATE THAT HAS TO BE DISTINGUISHED, and why it needs the raw file
---------------------------------------------------------------------
There are THREE states, and collapsing the last two is the whole trap:

1. the key is ABSENT from config.json  -> the user has never starred
   anything, so show the built-in defaults;
2. the key holds entries               -> those are the favorites;
3. the key holds an EMPTY LIST         -> the user starred and then
   unstarred everything. That is a CHOICE, and re-seeding it with the
   defaults would silently undo it. An empty chip row is the correct
   answer, with an empty state that says so.

``AuthConfig.common_slash_commands`` defaults to ``[]``, so by the time
config.json has been parsed into that model, states 1 and 3 are the same
value and are no longer tellable apart. So every read here goes to the
FILE, where key presence still exists. That also removes this endpoint
from the ``_auth_config_cache`` staleness question entirely, which is why
nothing in src/config.py had to change.

BACKWARD COMPATIBILITY
----------------------
Every existing entry is passed through BYTE FOR BYTE on a write, in its
original form. A user's hand-authored
``{"command": "/deploy", "description": "ship it"}`` survives starring
something else, and the historical bare-string form is what a newly
starred command is appended as, exactly as
``slash_command_labels.append_missing_commands`` has always done. Nothing
here rewrites an entry it did not have to touch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import config_writer
from src.core import slash_command_labels

logger = structlog.get_logger()

FAVORITES_KEY = "common_slash_commands"

MAX_FAVORITES = 40

COLORS_KEY = "slash_favorite_colors"

FAVORITE_COLORS = ("yellow", "green", "cyan", "violet", "coral")


class FavoritesError(ValueError):
    """A favorites operation could not be applied.

    Raised for a blank command and for exceeding ``MAX_FAVORITES``.
    Distinct from a JSON/IO failure so the route can answer 400 rather
    than 500.
    """


class FavoritesStale(FavoritesError):
    pass


def read_raw(config_path: Path) -> Tuple[Any, bool]:
    data = _load(config_path)
    return data.get(FAVORITES_KEY, []), FAVORITES_KEY in data


def _load(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Auth config file not found: {config_path}")
    try:
        with open(config_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {config_path}: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config shape in {config_path}: expected an object")
    return data


def resolve(raw: Any, declared: bool) -> List[Dict[str, str]]:
    if not declared:
        return slash_command_labels.normalize(
            slash_command_labels.DEFAULT_COMMON_COMMANDS
        )
    return slash_command_labels.normalize(raw if isinstance(raw, list) else [])


def is_favorite(raw: Any, declared: bool, command: str) -> bool:
    key = slash_command_labels.entry_command(command)
    if not key:
        return False
    return any(d["command"] == key for d in resolve(raw, declared))


def toggle(raw: Any, declared: bool, command: str, favorite: bool) -> List[Any]:
    key = slash_command_labels.entry_command(command)
    if not key:
        raise FavoritesError("command must not be blank")

    if declared:
        existing = list(raw) if isinstance(raw, list) else []
    else:
        existing = list(slash_command_labels.DEFAULT_COMMON_COMMANDS)

    if favorite:
        out = slash_command_labels.append_missing_commands(existing, [key])
        if len(out) > MAX_FAVORITES:
            raise FavoritesError(
                f"too many favorites: {len(out)} exceeds the limit of {MAX_FAVORITES}"
            )
        return out

    return [
        entry for entry in existing
        if slash_command_labels.entry_command(entry) != key
    ]


def write(config_path: Path, entries: List[Any]) -> None:
    if not config_path.exists():
        raise FileNotFoundError(f"Auth config file not found: {config_path}")

    entries = slash_command_labels.storage_form(entries)

    def merge(data: dict) -> dict:
        data = dict(data)
        data[FAVORITES_KEY] = entries
        _store_colors(data, data.get(COLORS_KEY), entries)
        return data

    config_writer.commit(config_path, merge)

    logger.info("slash_favorites_written", count=len(entries))


def colors_for(raw_colors: Any, commands: List[str]) -> Dict[str, str]:
    if not isinstance(raw_colors, dict):
        return {}
    wanted = set(commands)
    return {
        key: value for key, value in raw_colors.items()
        if isinstance(key, str) and key in wanted and value in FAVORITE_COLORS
    }


def _store_colors(data: Dict[str, Any], raw_colors: Any, entries: List[Any]) -> None:
    commands = [slash_command_labels.entry_command(e) for e in entries]
    kept = colors_for(raw_colors, commands)
    if kept:
        data[COLORS_KEY] = kept
    else:
        data.pop(COLORS_KEY, None)


def _current_entries(data: Dict[str, Any]) -> List[Any]:
    if FAVORITES_KEY not in data:
        return list(slash_command_labels.DEFAULT_COMMON_COMMANDS)
    raw = data.get(FAVORITES_KEY)
    return list(raw) if isinstance(raw, list) else []


def reorder(raw: Any, declared: bool, order: List[str]) -> List[Any]:
    existing = _current_entries({FAVORITES_KEY: raw} if declared else {})
    by_command = {slash_command_labels.entry_command(e): e for e in existing}
    wanted = [slash_command_labels.entry_command(c) for c in order]
    if len(wanted) != len(set(wanted)) or set(wanted) != set(by_command):
        raise FavoritesStale("the favorites changed since this view was drawn")
    return [by_command[c] for c in wanted]


def apply_order(config_path: Path, order: List[str]) -> None:

    def merge(data: dict) -> dict:
        data = dict(data)
        entries = reorder(data.get(FAVORITES_KEY), FAVORITES_KEY in data, order)
        data[FAVORITES_KEY] = slash_command_labels.storage_form(entries)
        _store_colors(data, data.get(COLORS_KEY), entries)
        return data

    config_writer.commit(config_path, merge)
    logger.info("slash_favorites_reordered", count=len(order))


def apply_color(config_path: Path, command: str, color: Optional[str]) -> None:
    key = slash_command_labels.entry_command(command)
    if not key:
        raise FavoritesError("command must not be blank")
    if color is not None and color not in FAVORITE_COLORS:
        raise FavoritesError("unknown colour")

    def merge(data: dict) -> dict:
        data = dict(data)
        entries = _current_entries(data)
        if key not in {slash_command_labels.entry_command(e) for e in entries}:
            raise FavoritesStale(f"{key} is not a favorite")
        commands = [slash_command_labels.entry_command(e) for e in entries]
        colors = colors_for(data.get(COLORS_KEY), commands)
        if color is None:
            colors.pop(key, None)
        else:
            colors[key] = color
        data[FAVORITES_KEY] = slash_command_labels.storage_form(entries)
        _store_colors(data, colors, entries)
        return data

    config_writer.commit(config_path, merge)
    logger.info("slash_favorite_color_set", command=key, color=color)


def payload(config_path: Path) -> Dict[str, Any]:
    data = _load(config_path)
    raw, declared = data.get(FAVORITES_KEY, []), FAVORITES_KEY in data
    details = resolve(raw, declared)
    colors = colors_for(data.get(COLORS_KEY), [d["command"] for d in details])
    details = [{**d, "color": colors.get(d["command"])} for d in details]
    return {
        "commands": slash_command_labels.commands_only(details),
        "command_details": details,
        "defaulted": not declared,
    }
