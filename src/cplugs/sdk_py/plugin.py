
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable, Dict, List, Optional

API_VERSION = "1.0"
MAX_FRAME_BYTES = 1024 * 1024


class HostError(Exception):

    def __init__(self, code: int, reason: str, data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"{code} {reason}")
        self.code = code
        self.reason = reason
        self.data = data or {}


class Host:

    def __init__(self, send: Callable[[str, Dict[str, Any]], Awaitable[Any]]) -> None:
        self.call = send
        self.sessions = _Namespace(send, "sessions")
        self.storage = _Namespace(send, "storage")
        self.notify = _Namespace(send, "notify")
        self.projects = _Namespace(send, "projects")

    async def http_fetch(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None,
                         body: Optional[str] = None) -> Dict[str, Any]:
        return await self.call("http.fetch", {"url": url, "method": method, "headers": headers or {}, "body": body})

    async def ai_call(self, feature: str, capability: str, input: Dict[str, Any]) -> Any:
        return (await self.call("ai.call", {"feature": feature, "capability": capability, "input": input}))["output"]

    async def process_snapshot(self) -> Dict[str, Any]:
        return await self.call("process.snapshot", {})

    async def mcp_config(self, session: Optional[str] = None) -> Dict[str, Any]:
        return await self.call("mcp.config", {} if session is None else {"session": session})

    async def mcp_links(self, session: Optional[str] = None) -> Dict[str, Any]:
        return await self.call("mcp.links", {} if session is None else {"session": session})

    async def log(self, level: str, event: str, **fields: Any) -> None:
        await self.call("log", {"level": level, "event": event, "fields": fields})


class _Namespace:

    def __init__(self, send: Callable[[str, Dict[str, Any]], Awaitable[Any]], prefix: str) -> None:
        self._send = send
        self._prefix = prefix

    def __getattr__(self, verb: str) -> Callable[..., Awaitable[Any]]:
        if verb.startswith("_"):
            raise AttributeError(verb)

        async def call(**params: Any) -> Any:
            return await self._send(f"{self._prefix}.{verb}", params)

        return call


class Plugin:

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_fns: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._routes: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._events: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._timers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self.settings: Dict[str, Any] = {}
        self.granted: List[str] = []
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._write: Optional[Callable[[Dict[str, Any]], None]] = None
        self.host = Host(self._call)

    def tool(self, name: str, description: str, input_schema: Optional[Dict[str, Any]] = None, gate: str = "read"):
        def deco(fn):
            self._tools[name] = {"name": name, "description": description, "inputSchema": input_schema or {"type": "object"},
                                 "gate": gate}
            self._tool_fns[name] = fn
            return fn
        return deco

    def route(self, name: str):
        def deco(fn):
            self._routes[name] = fn
            return fn
        return deco

    def on_event(self, family: str):
        def deco(fn):
            self._events[family] = fn
            return fn
        return deco

    def timer(self, name: str):
        def deco(fn):
            self._timers[name] = fn
            return fn
        return deco

    async def _call(self, method: str, params: Dict[str, Any]) -> Any:
        if self._write is None:
            raise RuntimeError("the plugin is not connected to a host")
        self._next_id += 1
        rid = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return await fut

    async def handle(self, method: str, params: Dict[str, Any]) -> Any:
        if method == "initialize":
            self.settings, self.granted = params.get("settings", {}), list(params.get("granted", []))
            return {"api_version": API_VERSION,
                    "capabilities": {"tools": bool(self._tools), "routes": bool(self._routes), "events": bool(self._events),
                                     "timers": bool(self._timers)},
                    "subscriptions": sorted(self._events)}
        if method == "ping":
            return {"ts": 0}
        if method == "shutdown":
            return {}
        if method == "tools/list":
            return {"tools": list(self._tools.values())}
        if method == "tools/call":
            text = await self._tool_fns[params["name"]](params.get("arguments", {}), params.get("caller", {}))
            return {"content": [{"type": "text", "text": text if isinstance(text, str) else json.dumps(text)}]}
        if method == "route.handle":
            return await self._routes[params["route"]](params)
        if method == "event.deliver":
            await self._events[params["family"]](params.get("seq"), params.get("payload"))
            return None
        if method == "timer.tick":
            await self._timers[params["name"]](params.get("scheduled_for"))
            return {}
        raise KeyError(method)

    def _dispatch_frame(self, frame: Dict[str, Any], tasks: set) -> None:
        if "method" not in frame:
            fut = self._pending.pop(frame.get("id"), None)
            if fut is not None and not fut.done():
                err = frame.get("error")
                if err:
                    fut.set_exception(HostError(err.get("code", 0), err.get("message", "error"), err.get("data")))
                else:
                    fut.set_result(frame.get("result"))
            return

        async def run() -> None:
            rid = frame.get("id")
            try:
                result = await self.handle(frame["method"], frame.get("params") or {})
                if rid is not None:
                    self._write({"jsonrpc": "2.0", "id": rid, "result": result if result is not None else {}})
            except (KeyError, TypeError, ValueError, HostError) as exc:
                if rid is not None:
                    self._write({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": type(exc).__name__}})

        task = asyncio.get_running_loop().create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def serve(self, reader: Optional[asyncio.StreamReader] = None, out: Any = None) -> None:
        loop = asyncio.get_running_loop()
        if reader is None:
            reader = asyncio.StreamReader(limit=MAX_FRAME_BYTES * 2)
            await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        sink = out if out is not None else sys.stdout.buffer

        def write(message: Dict[str, Any]) -> None:
            sink.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
            sink.flush()

        self._write = write
        tasks: set = set()
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            if isinstance(frame, dict):
                self._dispatch_frame(frame, tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
