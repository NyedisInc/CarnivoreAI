
from __future__ import annotations

from typing import Tuple

from src.core.session_group_style_ddl import (
    DDL_SESSION_GROUP_STYLES,
    SESSION_GROUP_STYLES_TABLE,
)

ICON_COLUMN = "icon"

DDL_V39_ADD_ICON = f"ALTER TABLE {SESSION_GROUP_STYLES_TABLE} ADD COLUMN {ICON_COLUMN} TEXT"

DDL_V39: Tuple[str, ...] = (DDL_SESSION_GROUP_STYLES, DDL_V39_ADD_ICON)

REVERSAL_SQL_V39: Tuple[str, ...] = ()
