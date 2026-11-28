
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api.auth import limiter
from src.core.mcp_usage import old_names as core_old_names, store as usage_store
from src.plugins.host import identity, renamed, routes as host_routes, runtime
from src.plugins.sdk import manifest as m, old_names
from src.plugins.sdk.definition import CplugDefinition
from src.plugins.sdk.routing import add_public_get, add_public_post, cplug_router, rate_limited

LIMIT = 2
OWNED_FILE = "alpha-extra"


def raw_manifest(cplug_id: str, **extra: Any) -> Dict[str, Any]:
    return {"schema": 1, "id": cplug_id, "name_key": f"cplug.{cplug_id}.name", "description_key": f"cplug.{cplug_id}.description",
            "version": "1.0.0", "icon": "plug", "author": "test", "min_app_version": "1.0.0", "tier": "builtin",
            "default_enabled": True, "surfaces": {"routes": False}, **extra}


@dataclass
class World:

    app: FastAPI
    state_dir: Path
    hooks: List[str] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    def host(self) -> runtime.Host:
        return runtime.host_for(self.app)


@rate_limited(f"{LIMIT}/minute")
async def limited(request: Request, response: Response) -> Dict[str, bool]:
    return {"ok": True}


def definitions(hooks: List[str]) -> Tuple[CplugDefinition, ...]:
    router = cplug_router("alpha")

    @router.post("/x")
    async def echo(body: Dict[str, Any]) -> Dict[str, Any]:
        """Answer the body sent. Output: dict."""
        return {"got": body}

    async def public_page() -> Dict[str, str]:
        return {"public": "yes"}

    async def record(which: str, ctx: Any) -> None:
        hooks.append(which)

    add_public_get(router, "alpha", "/p", public_page)
    add_public_post(router, "alpha", "/limited", limited)
    alpha = CplugDefinition(
        manifest=m.parse_manifest(raw_manifest("alpha", surfaces={"routes": True}, renamed_from="beta", owns={"files": [OWNED_FILE]})),
        router=router, on_start=lambda ctx: record("start", ctx), on_stop=lambda ctx: record("stop", ctx),
        before_purge=lambda ctx: record("before_purge", ctx))
    gamma = CplugDefinition(manifest=m.parse_manifest(raw_manifest("gamma", requires=["beta"])))
    return alpha, gamma


def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(identity, "RETIRED_IDS", frozenset({"beta"}))
    hooks: List[str] = []
    defs = definitions(hooks)
    runtime.check_definitions(defs)
    monkeypatch.setattr(runtime, "_definitions", renamed.resolve_requires(defs))
    monkeypatch.setattr(old_names, "_sink", None)
    monkeypatch.setattr(old_names, "_declared", {})
    monkeypatch.setattr(core_old_names, "_pending", Counter())
    core_old_names.install()
    monkeypatch.setattr(usage_store, "_default", usage_store.UsageStore(tmp_path / "mcp_usage.db"))
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    runtime.install(app, tmp_path)
    app.include_router(host_routes.build_router(), prefix="/api/v1")
    return World(app=app, state_dir=tmp_path, hooks=hooks)
