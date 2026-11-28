
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, FastAPI

from src.plugins.host import renamed, runtime, state as owner_state


def turn_on(host: runtime.Host, cplug_id: str = "taskmanager") -> owner_state.CplugState:
    d = runtime.find(cplug_id)
    assert d is not None, cplug_id
    return owner_state.update(host.state_dir, d.manifest, None,
                              lambda st: replace(st, enabled=True, grants=tuple(d.manifest.permissions)))


def isolated_host(monkeypatch: Any, app: Any, state_dir: Path, on: Iterable[str] = ("taskmanager",)) -> runtime.Host:
    host = runtime.Host(state_dir, app, publish=lambda topic: None)
    monkeypatch.setattr(app.state, "cplugs_host", host, raising=False)
    monkeypatch.setattr(runtime, "_host", host)
    for cplug_id in on:
        turn_on(host, cplug_id)
    return host


def include_task_manager_routes(app: FastAPI, router: APIRouter, cplug_id: str = "taskmanager") -> None:
    app.include_router(router, prefix="/api/v1")
    d = runtime.find(cplug_id)
    alias = renamed.alias_router(d) if d is not None else None
    if alias is not None:
        app.include_router(alias, prefix="/api/v1")
