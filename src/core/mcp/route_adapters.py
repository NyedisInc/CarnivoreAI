
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Iterable, Optional

from fastapi.encoders import jsonable_encoder

from src.core.mcp import federated, session_target
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok

READ = "read"
ARRANGE = "arrange"
ACT = "act"
_GATES = (READ, ARRANGE, ACT)


@dataclass
class Call:

    route: Callable[..., Any]
    request: Any
    args: dict
    target: Optional[session_target.SessionTarget] = None
    session_uuid: Optional[str] = None

    @property
    def tmux_name(self) -> str:
        t = self.target
        name = (t.info.tmux_session if t is not None and t.live else t.tmux_name if t is not None else None)
        if not name:
            raise ToolError("that session has no tmux name")
        return name

    @property
    def session_id(self) -> str:
        if self.target is None or not self.target.live:
            raise ToolError("that session is not live")
        return self.target.info.session.id


@dataclass(frozen=True)
class RouteTool:

    name: str
    route: str
    gate: str
    description: str
    invoke: Callable[[Call], Any]
    properties: dict = field(default_factory=dict)
    required: tuple = ()
    reach: Optional[str] = None
    needs_uuid: bool = False
    local_only: bool = True
    summary: Optional[Callable[[dict, Optional[session_target.SessionTarget]], str]] = None
    precheck: Optional[Callable[[dict, Optional[session_target.SessionTarget]], Awaitable[None]]] = None
    request_check: Optional[Callable[[Any], None]] = None
    example: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gate not in _GATES:
            raise ValueError(f"{self.name}: unknown gate {self.gate!r}")
        if self.gate == ACT and self.summary is None:
            raise ValueError(f"{self.name}: an ACT tool needs the summary the owner reads")


def route_function(spec: RouteTool) -> Callable[..., Any]:
    module, name = spec.route.split(":")
    return getattr(importlib.import_module(module), name)


def route_request(manager: Any) -> Any:
    from src.core.mcp.write_tools import _request

    return SimpleNamespace(app=_request(manager).app, scope={}, headers={}, query_params={})


def _schema(spec: RouteTool) -> dict:
    from src.core.mcp.common import _TARGET_SCHEMA

    return {**({"target": _TARGET_SCHEMA} if spec.reach else {}), **spec.properties}


def _check_args(spec: RouteTool, args: dict) -> None:
    allowed = set(_schema(spec))
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"{spec.name} does not take {', '.join(extra)}; it takes {', '.join(sorted(allowed)) or 'no arguments'}")
    missing = [k for k in ((("target",) if spec.reach else ()) + tuple(spec.required)) if k not in args]
    if missing:
        raise ToolError(f"{spec.name} needs {', '.join(missing)}")


async def _answer(spec: RouteTool, call: Call) -> dict:
    from fastapi import HTTPException

    from src.core.mcp.write_tools import _detail

    try:
        answer = spec.invoke(call)
        if inspect.isawaitable(answer):
            answer = await answer
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    except ValueError as exc:
        raise ToolError(f"{spec.name}: invalid arguments: {' '.join(str(exc).split())[:300]}") from exc
    return _ok(jsonable_encoder(answer))


def _handler(spec: RouteTool) -> Callable[[Any, AgentCaller, dict], Awaitable[dict]]:

    async def handler(manager: Any, caller: AgentCaller, args: dict) -> dict:
        _check_args(spec, args)
        target = uuid = None
        if spec.reach:
            resolver = session_target.TargetResolver(manager)
            target = await resolver.resolve(args, reach=spec.reach, tool=spec.name)
            if spec.local_only and target.live and federated.is_remote(target.info):
                raise ToolError(f"that session lives on a paired computer: call {spec.name} there")
            uuid = await resolver.uuid_of(target) if spec.needs_uuid else None
        if spec.precheck is not None:
            await spec.precheck(args, target)
        request = route_request(manager)
        if spec.request_check is not None:
            spec.request_check(request)

        def run_call() -> Call:
            return Call(route=route_function(spec), request=request, args=args, target=target, session_uuid=uuid)

        if spec.gate != ACT:
            return await _answer(spec, run_call())
        from src.core.mcp.write_tools import _as_result, park

        async def run(_approved: bool) -> dict:
            return await _answer(spec, run_call())

        live = target is not None and target.live
        target_id = target.info.session.id if live else (uuid or (target.session_uuid if target else "") or "")
        target_tmux = (target.info.tmux_session if live else target.tmux_name if target else "") or ""
        key = hashlib.sha256(json.dumps([spec.name, args], sort_keys=True, default=str).encode()).hexdigest()
        return await _as_result(park(manager, caller, target_id, target_tmux, spec.name, spec.summary(args, target),
                                     args, run, dedupe_key=key))

    handler.__name__ = spec.name
    handler.__doc__ = f"MCP adapter over {spec.route} ({spec.gate}). Inputs: manager, caller, args. Output: result."
    return handler


def tables(specs: Iterable[RouteTool]) -> tuple[dict, dict, frozenset]:
    reads: dict = {}
    writes: dict = {}
    for spec in specs:
        if spec.name in reads or spec.name in writes:
            raise ValueError(f"duplicate tool {spec.name}")
        row = (spec.description, _schema(spec), list(dict.fromkeys((["target"] if spec.reach else []) + list(spec.required))), _handler(spec))
        (reads if spec.gate == READ else writes)[spec.name] = row
    ungated = frozenset(s.name for s in specs if s.gate == ARRANGE)
    return reads, writes, ungated
