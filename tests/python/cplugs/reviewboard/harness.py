
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from fastapi import FastAPI

from src.cplugs.host import runtime, state as owner_state
from src.cplugs.huddle import board_port, service as task_manager_service
from src.cplugs.reviewboard import layout
from src.cplugs.huddle.store import TaskManagerStore
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.reviewboard import routes
from src.cplugs.reviewboard.scan import MARKER
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/reviewboard"
PANE = AgentCaller("ses_1", "cloude_a", "ses_1")


@dataclass
class Env:

    app: FastAPI
    host: runtime.Host
    root: Path
    published: List[str] = field(default_factory=list)

    @property
    def manager(self) -> Any:
        async def infos() -> list:
            return []

        return SimpleNamespace(app=self.app, gate_waited=True, list_session_infos=infos)

    def board(self, slug: str) -> Path:
        return layout.board_dir(self.root, slug) or self.root / slug

    def set_root(self, value: Any) -> None:
        d = runtime.find("reviewboard")
        owner_state.update(self.host.state_dir, d.manifest, None, lambda st: replace(st, settings={"boardsRoot": "" if value is None else str(value)}))

    def call(self, name: str, args: Dict[str, Any], caller: AgentCaller = PANE) -> Any:
        result = asyncio.run(tools.call_tool(self.manager, caller, name, args))
        text = result["content"][0]["text"]
        return (False, text) if result.get("isError") else (True, json.loads(text))


OWN_PROJECT = 12


def huddle_on(env: Env, monkeypatch: Any) -> Any:
    async def infos() -> list:
        return [SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id="ses_1"), project_id=OWN_PROJECT, host_key="local")]

    monkeypatch.setattr(task_manager_service, "project_names", lambda ctx: {"12": "carnivore", "13": "blog"})
    ctx = env.host.context("huddle", infos=infos, background=True)
    board_port.register(ctx)
    return ctx


def huddle_store(env: Env) -> TaskManagerStore:
    return TaskManagerStore(env.host.storage("huddle"), notify=lambda key: None)


def make_env(tmp: Path, *, on: bool = True) -> Env:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    (tmp / "state").mkdir()
    host = runtime.install(app, tmp / "state")
    published: List[str] = []
    host.publish = published.append
    root = tmp / "repo" / "design" / "boards"
    root.mkdir(parents=True)
    (tmp / "repo" / ".git").mkdir()
    (root / MARKER).write_text("marker\n")
    turn_on(host, "huddle")
    if on:
        turn_on(host, "reviewboard")
    env = Env(app, host, root, published)
    env.set_root(root)
    return env
