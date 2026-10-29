
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from src.cplugs.reviewboard import root
from src.cplugs.reviewboard.errors import BoardError, NoRoot
from src.cplugs.sdk import CplugContext, ToolError


def board_root(ctx: CplugContext) -> Path:
    return root.resolve_root(ctx.settings_now().get(root.SETTING), root.state_dir_of(ctx.storage.path))[0]


def explicit_root(ctx: CplugContext) -> Path:
    value, state = ctx.settings_now().get(root.SETTING), root.state_dir_of(ctx.storage.path)
    if root.is_default_value(state, root.DEFAULT_FOLDER, value):
        raise NoRoot("unset", root.REASONS["unset"])
    return root.check_root(value, state)


def http_error(exc: BoardError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc), **exc.extra})


def tool_error(exc: BoardError) -> ToolError:
    return ToolError(f"refused ({exc.code}): {exc}")
