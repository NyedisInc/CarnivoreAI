
from __future__ import annotations

import ast
import asyncio
import json
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from src.tui import api_client as api_mod
from src.tui.api_client import ApiClient, AuthRequired, LoginError
from src.tui.token_store import TokenPair, TokenStore

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8000"
SECRETS = ("acc-secret-1", "ref-secret-1", "acc-secret-2", "ref-secret-2")


class FakeServer:

    def __init__(self) -> None:
        self.valid_refresh = {"ref-secret-1"}
        self.refresh_calls = 0
        self.valid_access = {"acc-secret-1"}
        self.counter = 1

    def _pair(self) -> dict[str, Any]:
        self.counter += 1
        acc, ref = f"acc-secret-{self.counter}", f"ref-secret-{self.counter}"
        self.valid_access.add(acc)
        self.valid_refresh.add(ref)
        return {"success": True, "access_token": acc, "refresh_token": ref, "expires_in": 900}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/auth/verify":
            code = json.loads(request.content)["code"]
            if code == "429429":
                return httpx.Response(429)
            if code != "123456":
                return httpx.Response(401, json={"detail": "bad code"})
            return httpx.Response(200, json={"success": True, "access_token": "acc-secret-1",
                                             "refresh_token": "ref-secret-1", "expires_in": 900})
        if path == "/api/v1/auth/refresh":
            self.refresh_calls += 1
            tok = json.loads(request.content)["refresh_token"]
            if tok not in self.valid_refresh:
                return httpx.Response(401, json={"detail": "bad refresh"})
            self.valid_refresh.discard(tok)
            return httpx.Response(200, json=self._pair())
        if path == "/api/v1/auth/status":
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            return httpx.Response(200 if bearer in self.valid_access else 401)
        return httpx.Response(404)


class NoEvents:

    down = False

    def __init__(self) -> None:
        from src.tui.listing_store import ListingStore

        async def nothing() -> dict:
            return {}

        self.listing = ListingStore(nothing)

    def on_topics(self, fn):
        return lambda: None

    def topic_pushed(self, topic: str) -> bool:
        return False

    def start(self) -> None: ...

    async def stop(self) -> None: ...


def make_client(store: TokenStore, server: FakeServer) -> ApiClient:
    return ApiClient(store, BASE, transport=httpx.MockTransport(server.handler))


def seed(store: TokenStore, expires_in: float = 900) -> None:
    store.save(TokenPair("acc-secret-1", "ref-secret-1", time.time() + expires_in))


def test_file_is_0600_and_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    before = store.path.read_bytes()
    replaced: list[tuple[str, str]] = []

    def boom(src: str, dst: Any) -> None:
        replaced.append((str(src), str(dst)))
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save(TokenPair("x", "y", 1.0))
    assert store.path.read_bytes() == before
    assert replaced and Path(replaced[0][0]).parent == tmp_path and replaced[0][1] == str(store.path)
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_lock_contention_second_holder_waits(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    events: list[str] = []
    entered = threading.Event()

    def second() -> None:
        with TokenStore(tmp_path).locked():
            events.append("second")

    with store.locked():
        thread = threading.Thread(target=second)
        thread.start()
        entered.wait(0.3)
        assert events == []
        events.append("first-done")
    thread.join(5)
    assert events == ["first-done", "second"]


def test_two_terminals_spend_the_refresh_token_once(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    seed(store, expires_in=-10)
    server = FakeServer()
    a, b = make_client(store, server), make_client(store, server)

    async def run() -> list[int]:
        res = await asyncio.gather(a.request("GET", "/api/v1/auth/status"), b.request("GET", "/api/v1/auth/status"))
        await a.aclose(); await b.aclose()
        return [r.status_code for r in res]

    assert asyncio.run(run()) == [200, 200]
    assert server.refresh_calls == 1
    saved = store.load()
    assert saved is not None and saved.refresh_token == "ref-secret-2"


def test_401_with_refused_refresh_clears_pair_and_requires_login(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    server = FakeServer()
    server.valid_access.clear()
    server.valid_refresh.clear()
    client = make_client(store, server)

    async def run() -> None:
        with pytest.raises(AuthRequired):
            await client.request("GET", "/api/v1/auth/status")
        assert await client.check_session() is False
        await client.aclose()

    asyncio.run(run())
    assert store.load() is None and not store.path.exists()


def test_login_errors_and_loopback_only(tmp_path: Path) -> None:
    client = make_client(TokenStore(tmp_path), FakeServer())

    async def run() -> None:
        for code, reason in (("000000", "invalid"), ("429429", "rate_limited")):
            with pytest.raises(LoginError) as err:
                await client.login(code)
            assert err.value.reason == reason
        await client.login("123456")
        await client.aclose()

    asyncio.run(run())
    assert TokenStore(tmp_path).load() is not None
    with pytest.raises(ValueError):
        ApiClient(TokenStore(tmp_path), "http://example.com:8000")
    assert api_mod.server_base_url(5001) == "http://127.0.0.1:5001"


def test_no_token_reaches_logs_repr_or_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = TokenStore(tmp_path)
    server = FakeServer()
    client = make_client(store, server)
    seen: list[str] = []

    async def run() -> None:
        await client.login("123456")
        store.save(TokenPair("acc-secret-1", "ref-secret-1", time.time() - 5))
        await client.request("GET", "/api/v1/auth/status")
        server.valid_refresh.clear()
        store.save(TokenPair("acc-secret-2", "ref-secret-2", time.time() - 5))
        try:
            await client.request("GET", "/api/v1/auth/status")
        except AuthRequired as exc:
            seen.append(repr(exc) + str(exc))
        await client.aclose()

    with structlog.testing.capture_logs() as logs:
        asyncio.run(run())
    seen.append(repr(TokenPair("acc-secret-1", "ref-secret-1", 1.0)))
    out = capsys.readouterr()
    blob = json.dumps(logs, default=str) + out.out + out.err + "".join(seen)
    assert logs, "expected the client to log its refresh events"
    assert not [s for s in SECRETS if s in blob]


def test_tui_app_login_then_401_returns_to_login(tmp_path: Path) -> None:
    from src.tui.app import CarnivoreTui, LoginScreen, MainScreen

    store = TokenStore(tmp_path)
    server = FakeServer()

    async def run() -> None:
        app = CarnivoreTui(make_client(store, server), events=NoEvents())  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, LoginScreen)
            await pilot.press(*"123456", "enter")
            await pilot.pause(0.3)
            assert isinstance(app.screen, MainScreen)
            server.valid_access.clear()
            server.valid_refresh.clear()
            store.save(TokenPair("acc-secret-1", "ref-secret-1", time.time() + 900))
            assert await app.client.check_session() is False
            app.show_login()
            await pilot.pause()
            assert isinstance(app.screen, LoginScreen)

    asyncio.run(run())


def _forbidden(name: str) -> bool:
    return name in ("textual", "src.tui") or name.startswith(("textual.", "src.tui."))


def offenders(root: Path) -> list[str]:
    bad: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root.parent) if root.name == "src" else path.relative_to(root)
        if rel.parts[:2] == ("src", "tui"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if called in ("import_module", "__import__"):
                    names = [node.args[0].value]
            if any(_forbidden(n) for n in names):
                bad.append(str(path))
    return bad


def test_server_never_imports_textual_or_the_tui(tmp_path: Path) -> None:
    assert sum(1 for _ in (REPO / "src").rglob("*.py")) > 100
    assert offenders(REPO / "src") == []
    planted = {
        "a.py": "import textual\n", "b.py": "from src.tui import app\n", "c.py": "import src.tui.app\n",
        "d.py": "import importlib\nimportlib.import_module('textual.app')\n", "e.py": "__import__('src.tui')\n",
        "ok.py": "import json\nimportlib.import_module('json')\n",
    }
    for name, body in planted.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    assert sorted(Path(p).name for p in offenders(tmp_path)) == ["a.py", "b.py", "c.py", "d.py", "e.py"]


def test_cli_help_and_default_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    from src.tui.__main__ import build_parser

    parser = build_parser()
    assert parser.parse_args([]).command is None and parser.parse_args(["tui"]).command == "tui"
    with pytest.raises(SystemExit) as ex:
        parser.parse_args(["--help"])
    assert ex.value.code == 0 and "tui" in capsys.readouterr().out


def test_no_env_or_system_proxy_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, "http://10.9.9.9:3128")
    client = ApiClient(TokenStore(tmp_path), BASE)
    transport = client._http._transport_for_url(httpx.URL(BASE))
    assert type(transport) is httpx.AsyncHTTPTransport
    assert "Proxy" not in type(transport._pool).__name__
    assert client._http.follow_redirects is False
    asyncio.run(client.aclose())


def test_refresh_429_keeps_the_pair(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    seed(store, expires_in=-10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"})

    client = ApiClient(store, BASE, transport=httpx.MockTransport(handler))

    async def run() -> None:
        with pytest.raises(api_mod.ServerUnavailable) as info:
            await client.request("GET", "/api/v1/auth/status")
        assert info.value.retry_after == 7.0
        await client.aclose()

    asyncio.run(run())
    saved = store.load()
    assert saved is not None and saved.refresh_token == "ref-secret-1"


def test_second_401_does_not_delete_a_pair_another_terminal_saved(tmp_path: Path) -> None:
    store = TokenStore(tmp_path)
    seed(store)
    server = FakeServer()
    other = TokenPair("acc-other", "ref-other", time.time() + 900)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/status":
            if not hasattr(handler, "swapped") and request.headers["authorization"].endswith("acc-secret-2"):
                handler.swapped = True  # type: ignore[attr-defined]
                store.save(other)
            return httpx.Response(401)
        return server.handler(request)

    client = ApiClient(store, BASE, transport=httpx.MockTransport(handler))

    async def run() -> None:
        with pytest.raises(AuthRequired):
            await client.request("GET", "/api/v1/auth/status")
        await client.aclose()

    asyncio.run(run())
    saved = store.load()
    assert saved is not None and saved.refresh_token == "ref-other"
