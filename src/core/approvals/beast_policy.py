
from __future__ import annotations

from typing import Any, Callable, Dict, List

import structlog

from src.core.approvals.auto_answer.catalog import DEFAULT_SCOPE, NEVER_ANSWERED, RULE_INFOS, SCOPE_SETTING, SCOPES
from src.core.approvals.beast_grid import KIND_PROMPT, LOCKED_ROWS, MODE_OFF, MODE_ON, MODES, ROWS, UNCONFIRMED_ROWS, RowInfo, cell_defaults

logger = structlog.get_logger()

ModeReader = Callable[[], bool]


class GridPolicy:

    def __init__(self, read: Callable[[], Dict[str, Any]], *, is_armed: ModeReader, is_prompts_armed: ModeReader) -> None:
        self._read = read
        self._armed = is_armed
        self._prompts_armed = is_prompts_armed

    def mode_for(self, row: RowInfo) -> str:
        on = self._prompts_armed() if row.kind == KIND_PROMPT else self._armed()
        return MODE_ON if on else MODE_OFF

    def ticked(self, row: RowInfo, mode: str, values: Dict[str, Any]) -> bool:
        key = row.cell(mode)
        return (values[key] is True) if key in values else row.default(mode)

    def handles(self, row_id: str) -> bool:
        for row in ROWS:
            if row.id == row_id:
                return self.ticked(row, self.mode_for(row), self._read())
        return False

    def ticked_in(self, row_id: str, mode: str) -> bool:
        if mode not in MODES:
            return False
        for row in ROWS:
            if row.id == row_id:
                return self.ticked(row, mode, self._read())
        return False

    def rule_on(self, rule_id: str) -> bool:
        return self.handles(rule_id)

    def trust_scope(self) -> str:
        value = self._read().get(SCOPE_SETTING, DEFAULT_SCOPE)
        return value if value in SCOPES else DEFAULT_SCOPE

    def status(self) -> Dict[str, Any]:
        values = self._read()
        rows: List[Dict[str, Any]] = []
        for row in ROWS:
            mode = self.mode_for(row)
            rows.append({"id": row.id, "kind": row.kind, **{m: self.ticked(row, m, values) for m in MODES}, "mode": mode,
                         "handled_now": self.ticked(row, mode, values), "cells": {m: row.cell(m) for m in MODES}})
        risks = {i.id: i.risk for i in RULE_INFOS}
        for entry in rows:
            if entry["id"] in risks:
                entry["risk"] = risks[entry["id"]]
        return {"rows": rows, "cells": {key: {"value": values.get(key) if isinstance(values.get(key), bool) else default, "default": default}
                                        for key, default in cell_defaults().items()},
                "trust_scope": self.trust_scope(), "trust_scopes": list(SCOPES), "unconfirmed_rows": list(UNCONFIRMED_ROWS),
                "always_asks": list(LOCKED_ROWS),
                "never_answered_screens": list(NEVER_ANSWERED)}


def stored_settings() -> Dict[str, Any]:
    from src.config import settings  # noqa: PLC0415

    try:
        mcp = settings.load_auth_config().mcp
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("beast_policy_config_unreadable", error_type=type(exc).__name__)
        return {}
    cells = mcp.beast_grid if isinstance(mcp.beast_grid, dict) else {}
    return {**cells, SCOPE_SETTING: mcp.beast_trust_scope}


def current() -> GridPolicy:
    from src.core.mcp import beast_mode  # noqa: PLC0415

    return GridPolicy(stored_settings, is_armed=beast_mode.stored_armed, is_prompts_armed=beast_mode.stored_prompts_armed)
