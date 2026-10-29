
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.cplugs.devwidgetlab import capture, draft_routes, matrix
from src.cplugs.devwidgetlab.errors import LabError
from src.cplugs.sdk import CplugContext, cplug_context, cplug_router

router = cplug_router("devwidgetlab")
Ctx = Depends(cplug_context("devwidgetlab"))


class SidebarBody(BaseModel):
    """The state of the REAL left sidebar a capture draws (``web/src/widget-harness/sidebar/sidebar-state.ts``)."""

    model_config = ConfigDict(extra="forbid")
    width: Literal["min", "default", "wide", "max"] = "default"
    folded: bool = False
    area: Literal["closed", "glance", "full"] = "full"
    density: Literal["compact", "cozy", "detailed"] = "compact"


class CaptureBody(BaseModel):
    """``POST /capture``: what to draw. Every field is checked before a process starts."""

    model_config = ConfigDict(extra="forbid")
    widget: str = Field(pattern=capture.KEY_PATTERN.pattern)
    host: Literal["home", "terminal", "drawer", "popout"]
    size: str = Field(pattern=capture.NAME_PATTERN.pattern)
    theme: str = Field(pattern=capture.NAME_PATTERN.pattern)
    fixture: Literal["data", "empty", "stress"] = "data"
    state: Literal["normal", "menu"] = "normal"
    scenario: Optional[str] = Field(default=None, max_length=capture.MAX_SCENARIO_CHARS)
    sidebar: Optional[SidebarBody] = Field(default=None, description="Draw the widget in the real left sidebar in this state (the drawer host only)")

    @model_validator(mode="after")
    def _sidebar_is_the_drawer(self) -> "CaptureBody":
        if self.sidebar is not None and self.host != "drawer":
            raise ValueError("sidebar is the left drawer's state, so the host must be drawer")
        return self


class MatrixBody(BaseModel):
    """``POST /matrix``: whether to also write the catalog images, and optionally the one widget to gate."""

    model_config = ConfigDict(extra="forbid")
    catalog: bool = False
    only: Optional[str] = Field(default=None, pattern=capture.KEY_PATTERN.pattern)


def _http(exc: LabError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc)})


@router.get("/status")
async def get_status(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Whether a capture can run here. Output: {available, reason, captures_dir}."""
    return {**capture.availability(), "captures_dir": str(capture.captures_dir(ctx.storage.path))}


@router.post("/capture")
async def post_capture(body: CaptureBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Run one capture. Output: the capture's metadata (see :func:`capture.run_capture`)."""
    try:
        return await capture.run_capture(body.model_dump(), ctx.storage.path)
    except LabError as exc:
        raise _http(exc) from exc


@router.get("/fit-table")
async def get_fit_table(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The last fit table and the run's state. Output: see :func:`matrix.state`."""
    return matrix.state(ctx.storage.path)


@router.post("/matrix")
async def post_matrix(body: MatrixBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Start the whole-matrix run. Output: the state (``running`` true)."""
    try:
        return matrix.start(ctx.storage.path, body.catalog, body.only)
    except LabError as exc:
        raise _http(exc) from exc


draft_routes.register(router, Ctx)
