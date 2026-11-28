
from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pytest
from fastapi.testclient import TestClient

from src.api import catalog_publish_routes, session_crud_routes
from src.config import settings
from src.core.catalog import archive_client, hosted_api
from src.core.catalog.index_refresher import IndexRefresher
from src.core.catalog.services import build_catalog_services
from src.core.cli_command import service as cli_service
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.live_install_roots import LiveInstallRoots
from src.core.plugin_studio import dev_session
from src.core.session_manager import SessionManager
from src.core.skills.ledger import InstallLedger
from src.core.ui_preferences_store import UiPreferencesStore
from src.plugins.host import (
    developer_mode,
    dev_lease,
    owner_switch,
    runtime as host_runtime,
    secret_store,
    sidecar_boot,
    sidecar_registry,
    sideload_git,
    ui_slots,
)
from src.plugins.runtime import socket_server
from src.plugins.runtime.owner_tokens import OwnerTokens
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_surface import INDEX_PATH, FrozenClock, fixture_trust_root, keypairs
from tests.helpers.static_http import StaticServer, self_signed_cert, serve_directory
from tests.python.api_keys.conftest import bearer

DARWIN_SANDBOX = sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec")


class MemKeychain:

    def __init__(self) -> None:
        self.saved: Dict[Tuple[str, str], str] = {}

    def read(self, service: str, account: str) -> Optional[str]:
        return self.saved.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.saved[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.saved.pop((service, account), None) is not None


@dataclass
class ProbeRequest:

    method: str
    path: str
    headers: Dict[str, str]
    body: bytes


@dataclass
class ProbeRoute:

    status: int = 200
    body: bytes = b'{"ok":true}'
    headers: Dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})


class LocalHttpProbe:

    def __init__(self, server: ThreadingHTTPServer, base_url: str, routes: Dict[str, ProbeRoute]) -> None:
        self._server = server
        self.base_url = base_url
        self.routes = routes
        self._lock = threading.Lock()
        self.requests: List[ProbeRequest] = []
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def host_port(self) -> Tuple[str, int]:
        addr = self._server.server_address
        return str(addr[0]), int(addr[1])

    def set_route(self, path: str, *, status: int = 200, body: bytes = b"{}", headers: Optional[Dict[str, str]] = None) -> None:
        self.routes[path] = ProbeRoute(
            status=status,
            body=body,
            headers=dict(headers or {"Content-Type": "application/json"}),
        )

    def record(self, req: ProbeRequest) -> None:
        with self._lock:
            self.requests.append(req)

    def seen(self) -> List[ProbeRequest]:
        with self._lock:
            return list(self.requests)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


@contextlib.contextmanager
def serve_http_probe(
    routes: Optional[Dict[str, ProbeRoute]] = None,
    *,
    tls_cert: Optional[Tuple[Path, Path]] = None,
) -> Iterator[LocalHttpProbe]:
    route_map: Dict[str, ProbeRoute] = dict(routes or {})
    probe_holder: List[LocalHttpProbe] = []

    class _Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            path_only = self.path.split("?", 1)[0]
            if probe_holder:
                probe_holder[0].record(ProbeRequest(method=self.command, path=self.path, headers=hdrs, body=body))
            spec = route_map.get(self.path) or route_map.get(path_only)
            if spec is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(spec.status)
            for k, v in spec.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(spec.body)))
            self.end_headers()
            if self.command != "HEAD" and spec.body:
                self.wfile.write(spec.body)

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle()

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, _fmt: str, *_args: Any) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    scheme = "http"
    if tls_cert is not None:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(tls_cert[0]), keyfile=str(tls_cert[1]))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    port = httpd.server_address[1]
    probe = LocalHttpProbe(httpd, f"{scheme}://127.0.0.1:{port}", route_map)
    probe_holder.append(probe)
    try:
        yield probe
    finally:
        probe.close()


def git_run(cwd: Path, *args: str, env_extra: Optional[Mapping[str, str]] = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if env_extra:
        env.update(env_extra)
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True)
    return (done.stdout or "").strip()


def init_bare_git_repo(
    root: Path,
    files: Mapping[str, str | bytes],
    *,
    tag: Optional[str] = None,
    commit_msg: str = "init",
    exec_paths: Sequence[str] = (),
) -> Tuple[Path, Path, str]:
    work = root / "git_work"
    bare = root / "git_remote.git"
    work.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        dst = work / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dst.write_bytes(content)
        else:
            dst.write_text(content, encoding="utf-8")
        if rel in exec_paths:
            dst.chmod(0o755)
    git_run(work, "init", "-q", "-b", "main")
    git_run(work, "config", "user.email", "e2e@example.com")
    git_run(work, "config", "user.name", "E2E")
    git_run(work, "config", "commit.gpgsign", "false")
    git_run(work, "add", ".")
    git_run(work, "commit", "-q", "-m", commit_msg)
    if tag:
        git_run(work, "tag", "-a", tag, "-m", tag)
    sha = git_run(work, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare, work, sha


def wire_bare_github(monkeypatch: pytest.MonkeyPatch, bare_repo: Path, *, owner: str = "acme", repo: str = "demo") -> None:
    canonical_url = f"https://github.com/{owner}/{repo}.git"
    monkeypatch.setattr(sideload_git, "ALLOWED_PROTOCOLS", ("https", "file"))
    orig_config = sideload_git._config
    monkeypatch.setattr(
        sideload_git,
        "_config",
        lambda: [*orig_config(), "-c", f"url.file://{bare_repo}/.insteadOf={canonical_url}"],
    )


def safe_socket_path(state_dir: Path, install_key: str) -> Path:
    return socket_server.socket_path_for(state_dir, install_key)


@dataclass
class PluginsV3E2EWorld:

    app: Any
    client: TestClient
    state: Path
    config_path: Path
    host: host_runtime.Host
    rt: sidecar_boot.SidecarRuntime
    timer_scheduler: Any
    feed_fanout: Any
    plugin_bus: Any
    tokens: OwnerTokens
    ui_slots: ui_slots.UiSlotRegistry
    ledger: InstallLedger
    prefs: UiPreferencesStore
    keychain: MemKeychain
    index_refresher: IndexRefresher
    services: Any
    catalog: Any
    static_srv: StaticServer
    http_probe: Optional[LocalHttpProbe]
    owner_headers: Dict[str, str]
    api_headers: Dict[str, str]
    owner_token: str
    api_secret: str
    loop: asyncio.AbstractEventLoop
    clock: FrozenClock
    published: List[str]
    launched_sessions: List[Dict[str, Any]]
    monkeypatch: pytest.MonkeyPatch

    def consent_for(
        self,
        plugin_id: str,
        *,
        grant_all: bool = True,
        secrets: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
        r_row = self.client.get(f"/api/v1/cplugs/{plugin_id}", headers=self.owner_headers)
        assert r_row.status_code == 200, r_row.text
        row = r_row.json()
        r_sheet = self.client.get(f"/api/v1/cplugs/{plugin_id}/sheet", headers=self.owner_headers)
        assert r_sheet.status_code == 200, r_sheet.text
        sheet = r_sheet.json()
        perms = [p["name"] for p in sheet.get("permissions", [])] if grant_all else []
        ticks = [p["name"] for p in sheet.get("permissions", []) if p.get("needs_tick")] if grant_all else []
        slots = [s["slot"] for s in sheet.get("ui_slots", [])] if grant_all else []
        slot_ticks = [s["slot"] for s in sheet.get("ui_slots", []) if s.get("needs_tick")] if grant_all else []
        body: Dict[str, Any] = {
            "revision": row["revision"],
            "enabled": True,
            "grants": {"app": perms, "ui_slots": slots},
            "consent": {
                "digest": sheet["digest"],
                "body_sha": sheet["body_sha"],
                "grants_sha": sheet["grants_sha"],
                "ticks": ticks,
                "ui_slots_sha": sheet.get("ui_slots_sha"),
                "slot_ticks": slot_ticks,
            },
        }
        if secrets:
            body["secrets"] = dict(secrets)
        return row["revision"], sheet, body

    def sideload_and_enable(
        self,
        folder: Path,
        plugin_id: Optional[str] = None,
        *,
        grant_all: bool = True,
        secrets: Optional[Dict[str, str]] = None,
        settings_map: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        r_sl = self.client.post("/api/v1/cplug-owner/sideload", json={"path": str(folder)}, headers=self.owner_headers)
        assert r_sl.status_code == 200, r_sl.text
        pid = plugin_id or r_sl.json()["id"]
        self.rt.supervisor.override_index(pid, True)
        _rev, _sheet, put_body = self.consent_for(pid, grant_all=grant_all, secrets=secrets)
        if settings_map:
            put_body["settings"] = dict(settings_map)
        r_en = self.client.put(f"/api/v1/cplugs/{pid}", json=put_body, headers=self.owner_headers)
        assert r_en.status_code == 200, r_en.text
        return r_en.json()


@contextlib.contextmanager
def build_plugins_v3_world(
    tmp_path: Path,
    owner_jwt: str,
    key_store: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev_mode: bool = True,
    enable_sideload: bool = True,
    with_http_probe: bool = True,
    env_safe: bool = False,
) -> Iterator[PluginsV3E2EWorld]:
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)

    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")
    cli_service.write_shim(state)
    owner_switch.write(state, enable_sideload)

    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(developer_mode, "is_on", lambda: dev_mode)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: state)

    mem_kc = MemKeychain()
    monkeypatch.setattr(secret_store, "_Login", lambda: mem_kc)

    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)

    launched_sessions: List[Dict[str, Any]] = []

    async def _fake_create_session(_request: Any, body: Any, **_kw: Any) -> Dict[str, Any]:
        sid = f"ses_e2e_{len(launched_sessions) + 1}"
        rec = {
            "id": sid,
            "tmux_session": f"cl_{sid}",
            "agent_type": body.agent_type,
            "working_dir": body.working_dir,
            "opening_prompt": body.opening_prompt,
            "status": "active",
        }
        launched_sessions.append(rec)
        return rec

    monkeypatch.setattr(session_crud_routes, "create_session_with_extra", _fake_create_session)

    served = tmp_path / "served"
    served.mkdir(parents=True, exist_ok=True)
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert = self_signed_cert(tls_dir)
    assert cert is not None
    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    trust = fixture_trust_root(index_kp, publisher_kp)
    clock = FrozenClock()

    prev_codeload = archive_client.CODELOAD_BASE_URL
    prev_hosted_client = hosted_api.shared_client
    published: List[str] = []

    with serve_directory(served, tls_cert=cert) as static_srv:
        archive_client.CODELOAD_BASE_URL = static_srv.base_url
        index_url = f"{static_srv.base_url}/{INDEX_PATH}"
        catalog = build_catalog_services(
            index_url=lambda: index_url,
            api_base_url=lambda: "https://catalog.test.invalid/api/v1",
            clock=clock,
            open_db=lambda: connect(db_path_for(state)),
            trust_root=trust,
        )
        roots = LiveInstallRoots(settings_reader=StateOnlySettings(state))
        services = build_services(
            clock=clock,
            install_roots=roots,
            catalog=catalog,
            settings_reader=StateOnlySettings(state),
            ui_preferences=prefs,
        )
        conn = connect(db_path_for(state))
        ledger = InstallLedger(conn)
        cplugs_host = host_runtime.Host(state, app, publish=published.append)
        loop = asyncio.new_event_loop()
        rt = sidecar_boot.SidecarRuntime(cplugs_host, app, loop, env_safe=lambda: env_safe, app_version="9.9.9")
        refresher = IndexRefresher(catalog.index_cache)
        slot_reg = ui_slots.registry_for(state)
        app.state.sidecar_runtime = rt
        app.state.cplugs_host = cplugs_host
        app.state.services = services
        app.state.ui_preferences_store = prefs
        app.state.catalog_index_refresher = refresher
        app.state.session_manager = SessionManager()
        dev_lease.store_for(state).clear_all()
        _row, api_secret = key_store.create("e2e-script")
        catalog_publish_routes.clear_handle_cache(id(app))

        probe_cm = serve_http_probe() if with_http_probe else contextlib.nullcontext(None)
        with probe_cm as http_probe, TestClient(app) as tc:
            try:
                if tc.portal is not None:
                    tc.portal.call(rt.start)
                    tc.portal.call(rt.supervisor.set_index, None)
                    rt.supervisor.set_safe_mode(env_safe)
                yield PluginsV3E2EWorld(
                    app=app,
                    client=tc,
                    state=state,
                    config_path=config_path,
                    host=cplugs_host,
                    rt=rt,
                    timer_scheduler=rt.timer_scheduler,
                    feed_fanout=rt.feed_fanout,
                    plugin_bus=rt.plugin_bus,
                    tokens=rt.tokens,
                    ui_slots=slot_reg,
                    ledger=ledger,
                    prefs=prefs,
                    keychain=mem_kc,
                    index_refresher=refresher,
                    services=services,
                    catalog=catalog,
                    static_srv=static_srv,
                    http_probe=http_probe,
                    owner_headers=bearer(owner_jwt),
                    api_headers=bearer(api_secret),
                    owner_token=owner_jwt,
                    api_secret=api_secret,
                    loop=loop,
                    clock=clock,
                    published=published,
                    launched_sessions=launched_sessions,
                    monkeypatch=monkeypatch,
                )
            finally:
                if tc.portal is not None:
                    tc.portal.call(dev_session.manager_for(app).shutdown)
                    tc.portal.call(rt.stop)
                for attr in (
                    "sidecar_runtime",
                    "cplugs_host",
                    "services",
                    "ui_preferences_store",
                    "catalog_index_refresher",
                    "session_manager",
                    "plugin_studio_dev",
                ):
                    if hasattr(app.state, attr):
                        delattr(app.state, attr)
                conn.close()
                sidecar_registry.install(None)
                dev_lease.store_for(state).clear_all()
                hosted_api.shared_client = prev_hosted_client  # type: ignore[assignment]
                archive_client.CODELOAD_BASE_URL = prev_codeload
                loop.close()
