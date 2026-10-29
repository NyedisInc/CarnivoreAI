
from __future__ import annotations

import sqlite3
from typing import Any, List, Mapping, Tuple

import structlog

from src.core import item_settings_store as store

logger = structlog.get_logger()
KIND_WIDGET = "widget"


def apply_widget_settings(
    conn: sqlite3.Connection, settings: Mapping[str, Mapping[str, Any]]
) -> Tuple[List[str], List[str]]:
    applied: List[str] = []
    refused: List[str] = []
    for widget, values in settings.items():
        if not values:
            continue
        try:
            store.write_item(conn, KIND_WIDGET, widget, dict(values))
        except store.ItemUnknown:
            refused.append(f"{widget} has no settings on this install; its settings were skipped")
        except store.SettingRefused as exc:
            refused.append(f"{widget} setting '{exc.key}' was refused ({exc.code}); its settings were skipped")
        else:
            applied.append(widget)
    logger.info("board_import_settings", applied=len(applied), refused=len(refused))
    return applied, refused
