
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.cli_command import service as cli_service
from src.core.computers import membership
from src.core.computers.door import Door
from src.plugins.cli import auth_discovery
from src.tui import __main__ as tui_main
from src.core.cli_command.token_store import TokenPair, TokenStore


def test_tui_main_dispatches_plugin_before_importing_textual(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parents[3]
    code = (
        "import sys; "
        "from src.tui import __main__ as m; "
        "rc = m.main(['plugin', '--help']); "
        "assert rc == 0; "
        "assert 'textual' not in sys.modules, 'textual should not be imported for carnivore plugin CLI'"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + (f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else "")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "carnivore plugin" in proc.stdout

    out_dir = tmp_path / "clidemo"
    rc = tui_main.main(["plugin", "new", str(out_dir), "--template", "python"])
    assert rc == 0
    assert (out_dir / "carnivore.toml").is_file()
    _ = capsys.readouterr()


def test_write_runtime_info_and_discover_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    door = tmp_path / "door.sock"
    written = cli_service.write_runtime_info(state, 5123, door_sock=str(door))
    assert written == cli_service.runtime_info_path(state)
    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o600
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["port"] == 5123
    assert doc["pid"] == os.getpid()
    assert doc["door_sock"] == str(door)

    monkeypatch.delenv("CARNIVORE_URL", raising=False)
    live = auth_discovery.discover_runtime(state)
    assert live.base_url == "http://127.0.0.1:5123"
    assert live.door_sock == door
    assert live.pid == os.getpid()

    written.write_text(json.dumps({"host": "127.0.0.1", "port": 59999, "pid": 9999999, "door_sock": str(door)}), encoding="utf-8")
    stale = auth_discovery.discover_runtime(state)
    assert stale.pid is None
    assert stale.base_url != "http://127.0.0.1:59999"

    monkeypatch.setenv("CARNIVORE_URL", "http://127.0.0.1:5888/")
    overridden = auth_discovery.discover_runtime(state)
    assert overridden.base_url == "http://127.0.0.1:5888"


def test_door_cli_token_works_unjoined_and_persists_token_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    import tempfile

    monkeypatch.setenv("CARNIVORE_API_TOKEN", "")
    monkeypatch.setattr(membership, "first_run_state", lambda: "unpaired")

    sock_dir = Path(tempfile.mkdtemp(prefix="d", dir="/tmp"))
    os.chmod(sock_dir, 0o700)
    door_sock = sock_dir / "d.sock"
    state = tmp_path / "state"
    state.mkdir()

    issued_count = {"n": 0}

    async def fake_totp(_code: str) -> bool:
        return False

    async def fake_login(_store: Any) -> Dict[str, Any]:
        issued_count["n"] += 1
        return {
            "access_token": f"tok-door-{issued_count['n']}",
            "refresh_token": f"ref-door-{issued_count['n']}",
            "expires_in": 900,
        }

    loop = asyncio.new_event_loop()
    door = Door(str(door_sock), totp_ok=fake_totp, login=fake_login, setup_status=lambda: "pending")
    ready = threading.Event()
    stop_holder: list[asyncio.Event] = []

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        ev = asyncio.Event()
        stop_holder.append(ev)

        async def _main() -> None:
            await door.start()
            ready.set()
            await ev.wait()
            await door.stop()

        loop.run_until_complete(_main())

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    assert ready.wait(timeout=5.0)

    received_tokens: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            auth = self.headers.get("Authorization", "")
            received_tokens.append(auth)
            if self.path == "/api/v1/ping":
                if auth == "Bearer tok-expired":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"detail":"expired"}')
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/v1/auth/refresh":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(404)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
    srv_thread.start()
    try:
        base_url = f"http://127.0.0.1:{srv.server_port}"
        cli_service.write_runtime_info(state, srv.server_port, door_sock=str(door_sock))

        monkeypatch.setenv("CARNIVORE_API_TOKEN", "tok-env-priority")
        env_client = auth_discovery.CliHttpClient(state_dir=state)
        assert env_client.resolve_token() == "tok-env-priority"
        assert issued_count["n"] == 0

        monkeypatch.delenv("CARNIVORE_API_TOKEN", raising=False)
        client = auth_discovery.CliHttpClient(state_dir=state, base_url=base_url)
        tok = client.resolve_token()
        assert tok == "tok-door-1"
        assert issued_count["n"] == 1
        saved = TokenStore(state).load()
        assert saved is not None and saved.access_token == "tok-door-1"
        auth_file = state / "tui_auth.json"
        assert stat.S_IMODE(auth_file.stat().st_mode) == 0o600

        TokenStore(state).save(TokenPair(access_token="tok-expired", refresh_token="ref-dead", access_expires_at=time.time() + 300))
        sc, body = client.request("GET", "/api/v1/ping")
        assert sc == 200 and body == {"ok": True}
        assert received_tokens[-2:] == ["Bearer tok-expired", "Bearer tok-door-2"]
    finally:
        srv.shutdown()
        srv.server_close()
        if stop_holder:
            loop.call_soon_threadsafe(stop_holder[0].set)
        thread.join(timeout=5.0)
        loop.close()
        shutil.rmtree(sock_dir, ignore_errors=True)


def test_door_login_tokens_binds_family_to_signed_in_device_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import jwt
    from src.api.door_auth import door_login_tokens
    from src.config import settings
    from src.core.catalog.token_store import CatalogSession, MODE_BOUND, open_token_store

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)

    toks_unsigned = asyncio.run(door_login_tokens(None))
    fam_unsigned = jwt.decode(toks_unsigned["access_token"], options={"verify_signature": False})["fam"]
    with open_token_store(state) as store:
        assert store.client_get(fam_unsigned) is None

    now = int(time.time())
    with open_token_store(state) as store:
        store.save(
            CatalogSession(
                login="alice@example.com",
                access_token="dev-acc",
                access_expires_at=now + 3600,
                refresh_token="dev-ref",
                refresh_expires_at=now + 86400,
                provider="email",
            ),
        )
    toks_signed = asyncio.run(door_login_tokens(None))
    fam_signed = jwt.decode(toks_signed["access_token"], options={"verify_signature": False})["fam"]
    with open_token_store(state) as store:
        entry = store.client_get(fam_signed)
        assert entry is not None
        assert entry.mode == MODE_BOUND
        assert entry.login == "alice@example.com"
        assert entry.provider == "email"
