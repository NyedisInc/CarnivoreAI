
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
import uvicorn

from src.config import settings
from src.config.byoai import TargetRef
from src.core import project_writes
from src.core.byoai import calllog as byoai_calllog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore as ByoaiKeyStore
from src.core.byoai.store import ByoaiStore
from src.core.cli_command import service as cli_service
from src.core.computers import membership
from src.core.computers.door import Door
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import pending
from src.core.session_backend import SessionBackend
from src.core.session_manager import SessionManager
from src.core.session_output.tap import TAP
from src.core.tmux_listing import TmuxListing
from src.models.sessions import Session, SessionStatus
from src.plugins.host import (developer_mode, fetch_transport, netguard, owner_switch,
                              runtime as host_runtime, secret_store, sidecar_boot, sidecar_registry, sideload)
from tests.helpers.plugins_v3_e2e_world import (DARWIN_SANDBOX, MemKeychain, ProbeRoute,
                                                build_plugins_v3_world, serve_http_probe)
from tests.helpers.plugins_v3_polyglot_fixtures import (
    DEFAULT_MIT_LICENSE,
    build_bash_plugin,
    build_bun_plugin,
    build_c_binary_plugin,
    has_bun,
    has_cc,
    write_plugin_files,
)
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[3]


class _MemoryScrollbackBackend(SessionBackend):

    def __init__(self, session_id: str, working_dir: Path, scrollback: bytes) -> None:
        self.session_id, self.working_dir, self._scrollback = session_id, working_dir, scrollback
        self.tmux_session, self.on_output = f"cl_{session_id}", None

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    def resize(self, rows: int, cols: int) -> None:
        return None

    async def write(self, data: bytes) -> None:
        return None

    def is_alive(self) -> bool:
        return True

    def capture_scrollback(self, lines: int = 3000) -> bytes:
        text = self._scrollback.decode("utf-8", errors="replace").splitlines()
        return "\n".join(text[-lines:]).encode("utf-8")

    async def read_async(self) -> None:
        return None

    async def paste_and_submit(self, text: str, gate: Any = None) -> None:
        return None

    def discover_existing(self) -> TmuxListing:
        return TmuxListing(sessions=(), ok=True)


def _probe_tls_cert(directory: Path, dns_name: str = "probe.example.com") -> Tuple[Path, Path]:
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_name)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(dns_name), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "probe_cert.pem", directory / "probe_key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _poll_until(predicate: Any, timeout: float = 10.0, step: float = 0.05) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        val = predicate()
        if val:
            return val
        time.sleep(step)
    raise AssertionError("timed out waiting for condition")


def _enable_sideload(world: Any) -> None:
    sideload.set_switch(world.state, True, hours=None)


def _parse_tool_json(resp: Any) -> Dict[str, Any]:
    txt = resp.json()["text"]
    if txt.startswith("third-party data from ") and "\n" in txt:
        txt = txt.split("\n", 1)[1]
    return json.loads(txt)


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_real_sidecar_runtime_timer_scheduler_fires_and_cancels_in_sandbox(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = write_plugin_files(
        tmp_path / "src_timer",
        {
            "carnivore.toml": """
                schema = 2
                id = "timerplug"
                name = "Timer Plug"
                version = "1.0.0"
                kind = "plugin"
                description = "Real timer tick E2E plugin"
                author = "Tester"
                license = "MIT"

                [run]
                cmd = ["python3", "main.py"]
                mode = "rpc"

                [timers.beat]
                every_seconds = 5

                [mcp]
                [[mcp.tools]]
                name = "read_ticks"
                description = "Read recorded timer ticks"
                gate = "read"
                inputSchema = { type = "object", properties = {} }
            """,
            "main.py": """
                import os
                from pathlib import Path
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.timer("beat")
                async def on_beat(scheduled_for):
                    cur = (await plugin.host.storage.get(key="ticks"))["value"] or []
                    cur.append(int(scheduled_for))
                    await plugin.host.storage.put(key="ticks", value=cur)
                    files_dir = Path(".")
                    (files_dir / "tick_count.txt").write_text(str(len(cur)), encoding="utf-8")

                @plugin.tool("read_ticks", "Read recorded timer ticks", {"type": "object", "properties": {}}, gate="read")
                async def read_ticks(_args, _caller):
                    cur = (await plugin.host.storage.get(key="ticks"))["value"] or []
                    return {"count": len(cur), "ticks": cur}
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        _enable_sideload(world)
        world.timer_scheduler._min_interval = 1
        row = world.sideload_and_enable(pkg, "timerplug")
        assert row["state"] == "active"
        assert world.timer_scheduler.active_count("timerplug") == 1

        def _got_tick() -> Optional[Dict[str, Any]]:
            r = world.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": "timerplug", "tool": "read_ticks", "args": {}},
                headers=world.owner_headers,
            )
            if r.status_code != 200:
                return None
            payload = _parse_tool_json(r)
            return payload if payload["count"] >= 1 else None

        res = _poll_until(_got_tick, timeout=8.5, step=0.2)
        assert res["count"] >= 1 and res["ticks"][0] > 0

        tick_file = world.host.folder("timerplug") / "files" / "tick_count.txt"
        assert tick_file.is_file() and int(tick_file.read_text(encoding="utf-8")) >= 1

        cur_rev = world.client.get("/api/v1/cplugs/timerplug", headers=world.owner_headers).json()["revision"]
        r_off = world.client.put(
            "/api/v1/cplugs/timerplug",
            json={"revision": cur_rev, "enabled": False},
            headers=world.owner_headers,
        )
        assert r_off.status_code == 200
        assert world.timer_scheduler.active_count("timerplug") == 0
        assert world.rt.effects.cancel("timerplug")["timers"] == 0


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_real_tap_emit_feed_fanout_to_sandbox_exec_scrubs_ansi_and_secrets(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = write_plugin_files(
        tmp_path / "src_feed",
        {
            "carnivore.toml": """
                schema = 2
                id = "feedplug"
                name = "Feed Plug"
                version = "1.0.0"
                kind = "plugin"
                description = "Real FeedFanout E2E plugin"
                author = "Tester"
                license = "MIT"

                [run]
                cmd = ["python3", "main.py"]
                mode = "rpc"

                [permissions]
                read = ["feed.scrubbed"]

                [permissions.reasons]
                "feed.view: scrubbed" = "Reads scrubbed feed chunks for E2E verification"

                [events]
                on = ["feed.scrubbed"]

                [mcp]
                [[mcp.tools]]
                name = "seen_feed"
                description = "Return captured scrubbed feed events"
                gate = "read"
                inputSchema = { type = "object", properties = {} }
            """,
            "main.py": """
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.on_event("feed.scrubbed")
                async def on_feed(seq, payload):
                    items = (await plugin.host.storage.get(key="events"))["value"] or []
                    items.append({"seq": seq, "payload": payload})
                    await plugin.host.storage.put(key="events", value=items)

                @plugin.tool("seen_feed", "Return captured scrubbed feed events", {"type": "object", "properties": {}}, gate="read")
                async def seen_feed(_args, _caller):
                    return {"events": (await plugin.host.storage.get(key="events"))["value"] or []}
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )

    base_observers = TAP.observer_count()
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        _enable_sideload(world)
        row = world.sideload_and_enable(pkg, "feedplug")
        assert row["state"] == "active"
        assert TAP.observer_count() == base_observers + 1

        fake_secret = "sk-ant-api03-" + ("A9b8C7d6E5" * 4)
        TAP.emit("ses_feed_e2e", f"\x1b[31mbuild ok\x1b[0m token={fake_secret}\n".encode("utf-8"))

        def _has_event() -> Optional[Dict[str, Any]]:
            r = world.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": "feedplug", "tool": "seen_feed", "args": {}},
                headers=world.owner_headers,
            )
            if r.status_code != 200:
                return None
            data = _parse_tool_json(r)
            return data if data["events"] else None

        got = _poll_until(_has_event, timeout=8.0, step=0.1)
        ev = got["events"][0]["payload"]
        assert ev["session_id"] == "ses_feed_e2e"
        assert "build ok" in ev["text"] and "\x1b[" not in ev["text"] and fake_secret not in ev["text"]

        cur_rev = world.client.get("/api/v1/cplugs/feedplug", headers=world.owner_headers).json()["revision"]
        world.client.put(
            "/api/v1/cplugs/feedplug",
            json={"revision": cur_rev, "enabled": False},
            headers=world.owner_headers,
        )
        assert TAP.observer_count() == base_observers
    assert TAP.observer_count() == base_observers


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_real_owner_tool_read_and_inbox_plus_ui_v2_and_act_in_sandbox(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = write_plugin_files(
        tmp_path / "src_uiact",
        {
            "carnivore.toml": """
                schema = 2
                id = "uiactplug"
                name = "UI Act Plug"
                version = "1.0.0"
                kind = "plugin"
                description = "Real tool, UI v2, and act E2E plugin"
                author = "Tester"
                license = "MIT"

                [run]
                cmd = ["python3", "main.py"]
                mode = "rpc"

                [ui]
                routes = ["save_note"]

                [mcp]
                [[mcp.tools]]
                name = "echo_read"
                description = "Immediate read tool"
                gate = "read"
                inputSchema = { type = "object", properties = { msg = { type = "string" } } }

                [[mcp.tools]]
                name = "apply_write"
                description = "Inbox-gated write tool"
                gate = "inbox"
                inputSchema = { type = "object", properties = { value = { type = "string" } } }
            """,
            "main.py": """
                from cplug_sdk import Plugin

                plugin = Plugin()

                @plugin.tool("echo_read", "Immediate read tool", {"type": "object", "properties": {"msg": {"type": "string"}}}, gate="read")
                async def echo_read(args, _caller):
                    note = (await plugin.host.storage.get(key="note"))["value"]
                    return {"msg": args.get("msg", ""), "note": note}

                @plugin.tool("apply_write", "Inbox-gated write tool", {"type": "object", "properties": {"value": {"type": "string"}}}, gate="inbox")
                async def apply_write(args, _caller):
                    val = str(args.get("value", ""))
                    await plugin.host.storage.put(key="inbox_val", value=val)
                    return {"applied": val}

                @plugin.route("save_note")
                async def save_note(req):
                    note = str((req.get("body") or {}).get("note", ""))
                    await plugin.host.storage.put(key="note", value=note)
                    return {"status": 200, "body": {"saved": note}}

                @plugin.ui("widget")
                async def render_widget(_params):
                    note = (await plugin.host.storage.get(key="note"))["value"] or "empty"
                    inbox_val = (await plugin.host.storage.get(key="inbox_val"))["value"] or "none"
                    return {
                        "schema": 2,
                        "root": {
                            "type": "section",
                            "title": "UI Act Plug",
                            "children": [
                                {"type": "text", "value": f"note={note};inbox={inbox_val}"},
                                {
                                    "type": "button",
                                    "label": "Save",
                                    "action": {"call": "route", "route": "save_note", "payload": {"note": "btn"}},
                                },
                            ],
                        },
                    }
            """,
            "LICENSE.md": DEFAULT_MIT_LICENSE,
        },
    )

    store = pending.PendingActions()
    monkeypatch.setattr(pending, "get_store", lambda: store)

    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        _enable_sideload(world)
        world.sideload_and_enable(pkg, "uiactplug")

        r_read = world.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "uiactplug", "tool": "echo_read", "args": {"msg": "hi"}},
            headers=world.owner_headers,
        )
        assert r_read.status_code == 200, r_read.text
        assert _parse_tool_json(r_read) == {"msg": "hi", "note": None}

        approve_errors: List[Exception] = []

        def _approve_when_ready() -> None:
            try:
                assert world.client.portal is not None
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    items = store.list()
                    if items:
                        world.client.portal.call(store.approve, items[0]["id"])
                        return
                    time.sleep(0.02)
                raise TimeoutError("pending inbox item never appeared")
            except Exception as exc:  # noqa: BLE001
                approve_errors.append(exc)

        approver = threading.Thread(target=_approve_when_ready, daemon=True)
        approver.start()
        r_inbox = world.client.post(
            "/api/v1/cplug-owner/tool",
            json={"cplug_id": "uiactplug", "tool": "apply_write", "args": {"value": "approved-42"}},
            headers=world.owner_headers,
        )
        approver.join(timeout=5.0)
        assert not approve_errors, approve_errors
        assert r_inbox.status_code == 200, r_inbox.text
        assert _parse_tool_json(r_inbox) == {"applied": "approved-42"}

        r_act = world.client.post(
            "/api/v1/cplug-owner/act",
            json={"cplug_id": "uiactplug", "route": "save_note", "body": {"note": "from-act"}},
            headers=world.owner_headers,
        )
        assert r_act.status_code == 200, r_act.text
        assert r_act.json() == {"saved": "from-act"}

        r_ui = world.client.get("/api/v1/cplugs/uiactplug/ui/widget", headers=world.owner_headers)
        assert r_ui.status_code == 200, r_ui.text
        ui_body = r_ui.json()
        assert ui_body["stale"] is False and ui_body["document"]["schema"] == 2
        children = ui_body["document"]["root"]["children"]
        assert children[0]["value"] == "note=from-act;inbox=approved-42"
        assert children[1]["action"]["route"] == "save_note"


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_real_host_services_http_secret_sessions_projects_ledger_exports_ai_in_sandbox(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tls_cert = _probe_tls_cert(tmp_path, "probe.example.com")
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_cert[0]))
    secret_val = "tok_live_" + "e2e_probe_987654321"
    fake_scrollback_secret = "sk-ant-api03-" + ("Z1y2X3w4V5" * 4)
    ai_reply = json.dumps({
        "id": "chatcmpl-e2e", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "real-ai-summary"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }).encode("utf-8")

    with serve_http_probe(
        routes={
            "/echo": ProbeRoute(
                status=200,
                body=json.dumps({"probe": "ok", "echo": secret_val}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Echo": f"Bearer {secret_val}"},
            ),
        },
        tls_cert=tls_cert,
    ) as tls_probe, serve_http_probe(
        routes={"/v1/chat/completions": ProbeRoute(status=200, body=ai_reply)},
    ) as ai_probe:
        probe_port = tls_probe.host_port[1]
        orig_getaddrinfo, orig_send = socket.getaddrinfo, fetch_transport.StdlibTransport.send

        def _probe_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            if host == "probe.example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", int(port or 443)))]
            return orig_getaddrinfo(host, port, *args, **kwargs)

        def _probe_send(self_t: Any, **kw: Any) -> Any:
            if kw.get("host") == "probe.example.com" and kw.get("port") == 443:
                kw["ip"], kw["port"] = "127.0.0.1", probe_port
            return orig_send(self_t, **kw)

        monkeypatch.setattr(socket, "getaddrinfo", _probe_getaddrinfo)
        monkeypatch.setattr(fetch_transport.StdlibTransport, "send", _probe_send)
        netguard._peer_cache.clear()

        export_dir = tmp_path / "picked_exports"
        export_dir.mkdir(parents=True)

        pkg = write_plugin_files(
            tmp_path / "src_svcs",
            {
                "carnivore.toml": """
                    schema = 2
                    id = "svce2e"
                    name = "Svc E2E"
                    version = "1.0.0"
                    kind = "plugin"
                    description = "All HostServices sandbox E2E"
                    author = "Tester"
                    license = "MIT"

                    [run]
                    cmd = ["python3", "main.py"]
                    mode = "rpc"

                    [permissions]
                    read = ["sessions", "output", "ledger"]
                    write = ["exports"]
                    network = [{ host = "probe.example.com", methods = ["GET", "POST"], paths = ["/"], auth = { secret = "api_token", header = "Authorization", scheme = "Bearer" } }]
                    secrets = [{ key = "api_token", label = "API Token" }]
                    app = ["ai_features:cplug.svce2e.summarize"]

                    [permissions.reasons]
                    "sessions.read" = "Reads live sessions for E2E test"
                    "sessions.output" = "Reads scrubbed scrollback output"
                    "ledger.read" = "Reads provider ledger summary"
                    "exports.write" = "Writes export artifact into picked folder"
                    "ai_features:cplug.svce2e.summarize" = "Calls host AI gateway to summarize"

                    [ai_features.summarize]
                    capability = "chat"
                    calls_per_day = 10
                    tokens_per_day = 5000

                    [settings_schema]
                    version = 1

                    [settings_schema.fields.picked_folders]
                    kind = "string"
                    labelKey = "cplug.svce2e.picked_folders"
                    default = ""
                    maxLength = 1024

                    [mcp]
                    [[mcp.tools]]
                    name = "probe_all"
                    description = "Exercise all HostServices from inside sandbox-exec"
                    gate = "read"
                    inputSchema = { type = "object", properties = { session_ref = { type = "string" }, export_dir = { type = "string" } } }
                """,
                "main.py": """
                    import base64
                    from cplug_sdk import HostError, Plugin

                    plugin = Plugin()

                    @plugin.tool("probe_all", "Exercise all HostServices from inside sandbox-exec", {"type": "object", "properties": {"session_ref": {"type": "string"}, "export_dir": {"type": "string"}}}, gate="read")
                    async def probe_all(args, _caller):
                        sid, exp_dir = args["session_ref"], args["export_dir"]
                        fetch_res = await plugin.host.http_fetch(
                            "https://probe.example.com/echo", method="POST",
                            headers={"Authorization": "Bearer $SECRET:api_token"}, body='{"hi":1}',
                        )
                        ssrf_code = None
                        try:
                            await plugin.host.http_fetch("http://127.0.0.1:9/steal")
                        except HostError as exc:
                            ssrf_code = exc.reason

                        return {
                            "fetch": fetch_res, "ssrf_code": ssrf_code,
                            "sessions": (await plugin.host.sessions.list())["sessions"],
                            "session": (await plugin.host.sessions.get(ref=sid))["session"],
                            "output": (await plugin.host.sessions.output(ref=sid, lines=20))["lines"],
                            "permission_mode": (await plugin.host.sessions.permission_mode(ref=sid))["mode"],
                            "projects": (await plugin.host.projects.list())["projects"],
                            "ledger": await plugin.host.call("ledger.read", {}),
                            "export": await plugin.host.call("exports.write", {"folder": exp_dir, "name": "report.txt", "bytes": base64.b64encode(b"sandbox-export-ok").decode("ascii")}),
                            "ai": await plugin.host.ai_call("cplug.svce2e.summarize", "chat", {"prompt": "Summarize build"}),
                        }
                """,
                "LICENSE.md": DEFAULT_MIT_LICENSE,
            },
        )

        with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch, with_http_probe=False) as world:
            _enable_sideload(world)
            mgr = SessionManager()
            sess = Session(
                id="ses_e2e_real",
                working_dir=str(tmp_path),
                status=SessionStatus.RUNNING,
                agent_type="codex",
                tmux_name="cl_ses_e2e_real",
            )
            backend = _MemoryScrollbackBackend(
                "ses_e2e_real",
                tmp_path,
                f"\x1b[32mline one\x1b[0m\naccept edits\nkey={fake_scrollback_secret}\n".encode("utf-8"),
            )
            mgr._registry.register(sess, backend)
            world.app.state.session_manager = mgr

            proj_dir = tmp_path / "e2e_proj"
            proj_dir.mkdir(parents=True)
            conn = connect(db_path_for(world.state))
            try:
                project_writes.create_project(conn, name="E2E Project", path=str(proj_dir))
            finally:
                conn.close()

            byoai_store = ByoaiStore(world.config_path, keys=ByoaiKeyStore(backend=MemKeychain()))
            conn_cfg = byoai_store.add_connection(preset="ollama", base_url=f"{ai_probe.base_url}/v1")
            byoai_store.set_feature("cplug.svce2e.summarize", TargetRef(connection=conn_cfg.id, model="llama3.2"))
            gateway = Gateway(byoai_store, byoai_calllog.CallLog(world.state), ByoaiKeyStore(backend=MemKeychain()))
            world.host.ai_gateway = lambda: gateway

            world.sideload_and_enable(
                pkg, "svce2e",
                secrets={"api_token": secret_val},
                settings_map={"picked_folders": str(export_dir)},
            )

            r_call = world.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": "svce2e", "tool": "probe_all", "args": {"session_ref": "ses_e2e_real", "export_dir": str(export_dir)}},
                headers=world.owner_headers,
            )
            assert r_call.status_code == 200, r_call.text
            out = _parse_tool_json(r_call)

            assert out["fetch"]["status"] == 200
            assert "[redacted]" in out["fetch"]["body"] and secret_val not in out["fetch"]["body"]
            assert "x-echo" not in out["fetch"]["headers"]
            assert any(r.path == "/echo" and r.headers.get("authorization") == f"Bearer {secret_val}" for r in tls_probe.seen())
            assert out["ssrf_code"] is not None

            assert any(s["id"] == "ses_e2e_real" for s in out["sessions"])
            assert out["session"]["id"] == "ses_e2e_real"
            joined_lines = "\n".join(out["output"])
            assert "line one" in joined_lines and "\x1b[" not in joined_lines and fake_scrollback_secret not in joined_lines
            assert out["permission_mode"] == "acceptEdits"

            assert any(p["name"] == "E2E Project" for p in out["projects"])
            assert isinstance(out["ledger"]["accounts"], list)
            assert Path(out["export"]["path"]).read_bytes() == b"sandbox-export-ok"
            assert out["ai"] == "real-ai-summary"
            assert any(r.path == "/v1/chat/completions" for r in ai_probe.seen())


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
def test_real_carnivore_bin_subprocess_cli_new_check_test_install_end_to_end(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.main import app

    state = tmp_path / "state"
    state.mkdir(parents=True)
    ensure_db_migrated(state, 4, "0.8.2")
    shim = cli_service.write_shim(state, root=REPO_ROOT, python=sys.executable)
    owner_switch.write(state, True)
    sideload.set_switch(state, True, hours=None)

    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(state))
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: state)
    monkeypatch.setattr(secret_store, "_Login", lambda: MemKeychain())
    monkeypatch.setattr(membership, "first_run_state", lambda: "unpaired")

    sock_dir = Path(tempfile.mkdtemp(prefix="d", dir="/tmp"))
    os.chmod(sock_dir, 0o700)
    door_sock = sock_dir / "d.sock"

    async def _fake_totp(_code: str) -> bool:
        return False

    async def _fake_login(_store: Any) -> Dict[str, Any]:
        return {"access_token": owner_jwt, "refresh_token": "ref-e2e", "expires_in": 900}

    door_loop = asyncio.new_event_loop()
    door = Door(str(door_sock), totp_ok=_fake_totp, login=_fake_login, setup_status=lambda: "pending")
    door_ready = threading.Event()
    door_stop: List[asyncio.Event] = []

    def _run_door() -> None:
        asyncio.set_event_loop(door_loop)
        ev = asyncio.Event()
        door_stop.append(ev)

        async def _main() -> None:
            await door.start()
            door_ready.set()
            await ev.wait()
            await door.stop()

        door_loop.run_until_complete(_main())

    door_thread = threading.Thread(target=_run_door, daemon=True)
    door_thread.start()
    assert door_ready.wait(timeout=5.0)

    rt_holder: List[sidecar_boot.SidecarRuntime] = []

    @contextlib.asynccontextmanager
    async def _cli_lifespan(target_app: Any):
        loop = asyncio.get_running_loop()
        host = host_runtime.Host(state, target_app, publish=lambda _t: None)
        rt = sidecar_boot.SidecarRuntime(host, target_app, loop, env_safe=lambda: False, app_version="9.9.9")
        target_app.state.cplugs_host, target_app.state.sidecar_runtime = host, rt
        rt_holder.append(rt)
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()
            for attr in ("sidecar_runtime", "cplugs_host"):
                if hasattr(target_app.state, attr):
                    delattr(target_app.state, attr)

    orig_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _cli_lifespan

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.bind(("127.0.0.1", 0))
    tcp_sock.listen(16)
    port = tcp_sock.getsockname()[1]
    cli_service.write_runtime_info(state, port, door_sock=str(door_sock))

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    srv_thread = threading.Thread(target=server.run, kwargs={"sockets": [tcp_sock]}, daemon=True)
    srv_thread.start()

    try:
        _poll_until(lambda: bool(rt_holder) and server.started, timeout=10.0)
        cli_tmp = tmp_path / "cli_tmp"
        cli_tmp.mkdir(parents=True)
        env = {**os.environ, "HOME": str(fake_home), "CLOUDE_STATE_DIR": str(state),
               "TMPDIR": str(cli_tmp), "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("CARNIVORE_API_TOKEN", None)
        env.pop("CARNIVORE_URL", None)

        pkg_dir = tmp_path / "clisub"
        for argv, timeout_s in (
            (["plugin", "new", "clisub", "--template", "python", "--dir", str(pkg_dir), "--json"], 30),
            (["plugin", "check", str(pkg_dir), "--json"], 30),
            (["plugin", "test", str(pkg_dir), "--json"], 60),
            (["plugin", "install", str(pkg_dir), "--from", "local", "-y", "--json"], 30),
        ):
            done = subprocess.run([str(shim), *argv], cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=timeout_s, check=False)
            assert done.returncode == 0, f"{argv}: {done.stderr}\n{done.stdout}"
            parsed = json.loads(done.stdout)
            if "ok" in parsed:
                assert parsed["ok"] is True

        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=bearer(owner_jwt), timeout=15.0) as hc:
            row = hc.get("/api/v1/cplugs/clisub")
            assert row.status_code == 200, row.text
            assert row.json()["enabled"] is True and row.json()["state"] == "active"

            tool_resp = hc.post("/api/v1/cplug-owner/tool", json={"cplug_id": "clisub", "tool": "clisub_hello", "args": {}})
            assert tool_resp.status_code == 200, tool_resp.text
            txt = tool_resp.json()["text"]
            assert "third-party data from clisub" in txt and txt.endswith("hello")
    finally:
        server.should_exit = True
        srv_thread.join(timeout=10.0)
        tcp_sock.close()
        app.router.lifespan_context = orig_lifespan
        sidecar_registry.install(None)
        if door_stop:
            door_loop.call_soon_threadsafe(door_stop[0].set)
        door_thread.join(timeout=5.0)
        door_loop.close()
        shutil.rmtree(sock_dir, ignore_errors=True)


@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec")
def test_polyglot_rpc_fixtures_pass_sandbox_integrity_and_tool_call(
    tmp_path: Path,
    owner_jwt: str,  # noqa: F811
    key_store: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with build_plugins_v3_world(tmp_path, owner_jwt, key_store, monkeypatch) as world:
        _enable_sideload(world)
        targets: List[Tuple[str, Path, str]] = [
            ("bashrpc", build_bash_plugin(tmp_path / "poly", plugin_id="bashrpc", mode="rpc"), "bash-rpc"),
        ]
        if has_bun():
            targets.append(("bunrpc", build_bun_plugin(tmp_path / "poly", plugin_id="bunrpc", mode="rpc"), "bun-rpc"))
        if has_cc():
            targets.append(("cbinrpc", build_c_binary_plugin(tmp_path / "poly", plugin_id="cbinrpc", mode="rpc"), "binary-rpc"))

        for pid, folder, expected_rt in targets:
            row = world.sideload_and_enable(folder, pid)
            assert row["state"] == "active", row
            r_tool = world.client.post(
                "/api/v1/cplug-owner/tool",
                json={"cplug_id": pid, "tool": "ping", "args": {"msg": "ok"}},
                headers=world.owner_headers,
            )
            assert r_tool.status_code == 200, f"{pid} failed: {r_tool.status_code} {r_tool.text}"
            payload = r_tool.json()["result"]
            assert payload["runtime"] == expected_rt, (pid, payload)
