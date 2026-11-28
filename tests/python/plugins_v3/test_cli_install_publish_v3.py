
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api import catalog_publish_routes
from src.core.catalog import archive_client, hosted_api
from src.core.catalog import client as catalog_client
from src.core.catalog.index_refresher import IndexRefresher
from src.core.catalog.services import build_catalog_services
from src.core.catalog.token_store import CatalogSession, open_token_store
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills import kinds
from src.core.skills.manifest_rules import check_manifest
from src.core.skills.stage import stage_archive
from src.core.skills.validate import ARCHIVE_INVALID, ArchiveRefused, validate_archive
from src.core.ui_preferences_store import UiPreferencesStore
from src.plugins.cli import main as cli_main
from src.plugins.cli.install_publish import detect_source, run_install, run_publish
from src.plugins.host import developer_mode, runtime, sidecar_boot, sidecar_registry, sideload_git
from src.plugins.host import state as owner_state
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_surface import (
    FIXTURE_REPO,
    INDEX_PATH,
    FrozenClock,
    build_skill,
    fixture_trust_root,
    keypairs,
    publish_index,
    serve_archive,
    skill_item,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary
from tests.helpers.static_http import self_signed_cert, serve_directory
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
WAREZSMOKE_FIXTURE = ROOT / "tests" / "fixtures" / "cplugs" / "warezsmoke"
SUBMISSION_ID = "ab" * 16


class _TestClientCliAdapter:

    def __init__(self, tc: TestClient, headers: Dict[str, str]) -> None:
        self._tc = tc
        self._headers = dict(headers)
        self.calls: List[Tuple[str, str, Optional[Dict[str, Any]], int]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Tuple[int, Any]:
        _ = timeout
        resp = self._tc.request(method, path, json=json_body, headers=self._headers)
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text}
        self.calls.append((method, path, json_body, resp.status_code))
        return resp.status_code, body


def _git(*args: str, cwd: Optional[Path] = None) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def live_app(tmp_path: Path, owner_jwt, key_store, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from src.main import app

    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")

    served = tmp_path / "served"
    served.mkdir(parents=True, exist_ok=True)
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert = self_signed_cert(tls_dir)
    assert cert is not None

    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    trust = fixture_trust_root(index_kp, publisher_kp)
    clock = FrozenClock()

    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)

    sent_hosted: List[httpx.Request] = []
    hosted_routes: Dict[Tuple[str, str], Tuple[int, Any]] = {
        ("GET", "/me"): (200, {"provider": "github", "login": "alice", "handle": "alice", "handle_status": "approved", "registered": True}),
        ("POST", "/submissions"): (
            201,
            {"submission_id": SUBMISSION_ID, "status": "pending", "item_id": "alice/pubplug", "version": "0.1.0"},
        ),
        ("GET", "/submissions/mine"): (200, {"submissions": []}),
    }

    def _hosted_handler(request: httpx.Request) -> httpx.Response:
        sent_hosted.append(request)
        path = request.url.path
        for suffix in ("/me", "/submissions/mine", "/submissions"):
            if path.endswith(suffix):
                key = (request.method.upper(), suffix)
                if key in hosted_routes:
                    sc, body = hosted_routes[key]
                    return httpx.Response(sc, json=body)
        return httpx.Response(404, json={"detail": f"unhandled {request.method} {path}"})

    fake_hosted = httpx.AsyncClient(transport=httpx.MockTransport(_hosted_handler), follow_redirects=False)

    async def _shared_hosted_client() -> httpx.AsyncClient:
        return fake_hosted

    prev_hosted_client = hosted_api.shared_client
    hosted_api.shared_client = _shared_hosted_client  # type: ignore[assignment]
    prev_codeload = archive_client.CODELOAD_BASE_URL

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

        @contextlib.asynccontextmanager
        async def _lifespan(_app: Any):
            await catalog_client.init(verify=str(cert[0]))
            try:
                yield
            finally:
                await catalog_client.shutdown()

        monkeypatch.setattr(app.router, "lifespan_context", _lifespan)
        monkeypatch.setattr(developer_mode, "is_on", lambda: True)

        host = SimpleNamespace(
            state_dir=state,
            publish=lambda _topic: None,
            publish_coalesced=lambda *_a, **_kw: None,
            install_key=lambda name: f"inst-{name}",
            enabled=lambda pid: (
                owner_state.get(state, d.manifest).enabled
                if (d := runtime.find(pid)) is not None
                else False
            ),
        )
        loop = asyncio.new_event_loop()
        rt = sidecar_boot.SidecarRuntime(host, app, loop, env_safe=lambda: False, app_version="9.9.9")

        prev_services = getattr(app.state, "services", None)
        prev_prefs = getattr(app.state, "ui_preferences_store", None)
        prev_refresher = getattr(app.state, "catalog_index_refresher", None)
        app.state.services = services
        app.state.ui_preferences_store = prefs
        app.state.catalog_index_refresher = IndexRefresher(catalog.index_cache)
        app.state.sidecar_runtime = rt
        app.state.cplugs_host = runtime.Host(state, app)

        with open_token_store(state) as store:
            store.save(
                CatalogSession(
                    login="alice",
                    access_token="HELD-ACCESS-SECRET",
                    access_expires_at=4_000_000_000,
                    refresh_token="HELD-REFRESH-SECRET",
                    refresh_expires_at=4_100_000_000,
                )
            )

        _row, api_secret = key_store.create("cli-script")
        catalog_publish_routes.clear_handle_cache(id(app))
        with TestClient(app) as tc:
            try:
                yield SimpleNamespace(
                    tc=tc,
                    app=app,
                    state=state,
                    served=served,
                    index_kp=index_kp,
                    publisher_kp=publisher_kp,
                    owner_cli=_TestClientCliAdapter(tc, bearer(owner_jwt)),
                    key_cli=_TestClientCliAdapter(tc, bearer(api_secret)),
                    owner_headers=bearer(owner_jwt),
                    sent_hosted=sent_hosted,
                    hosted_routes=hosted_routes,
                    catalog=catalog,
                    clock=clock,
                    rt=rt,
                )
            finally:
                catalog_publish_routes.clear_handle_cache(id(app))
                if tc.portal is not None:
                    tc.portal.call(rt.supervisor.shutdown)
                for attr in ("sidecar_runtime", "cplugs_host"):
                    if hasattr(app.state, attr):
                        delattr(app.state, attr)
                app.state.services = prev_services
                app.state.ui_preferences_store = prev_prefs
                app.state.catalog_index_refresher = prev_refresher
                sidecar_registry.install(None)
                loop.close()
                archive_client.CODELOAD_BASE_URL = prev_codeload
                hosted_api.shared_client = prev_hosted_client
                asyncio.run(fake_hosted.aclose())


def test_detect_source_classification(tmp_path: Path) -> None:
    local_dir = tmp_path / "my-plug"
    local_dir.mkdir()
    k1, s1 = detect_source(str(local_dir))
    assert k1 == "local" and s1 == {"path": str(local_dir.resolve())}

    k2, s2 = detect_source("acme/cool-plugin@v1.2.3")
    assert k2 == "github" and s2 == {"url": "https://github.com/acme/cool-plugin.git", "ref": "v1.2.3"}

    k3, s3 = detect_source("https://github.com/acme/cool-plugin.git")
    assert k3 == "github" and s3 == {"url": "https://github.com/acme/cool-plugin.git"}

    k4, s4 = detect_source("nyedis/demo-plugin")
    assert k4 == "warez" and s4 == {"item_id": "nyedis/demo-plugin"}


def test_run_install_local_and_enable_contract(live_app: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = live_app
    plug = tmp_path / "localplug"
    assert cli_main(["new", "localplug", "--template", "python", "--dir", str(plug)]) == 0

    assert run_install(str(plug), client=w.owner_cli, assume_yes=True) == 1
    assert "sideload_off" in capsys.readouterr().err

    assert w.tc.put("/api/v1/cplug-owner/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
    assert w.tc.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
    assert run_install(str(plug), client=w.key_cli, assume_yes=True) == 1
    assert "api_key_forbidden" in capsys.readouterr().err

    assert run_install(str(plug), client=w.owner_cli, assume_yes=True, as_json=True) == 0
    out_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out_doc["id"] == "localplug"
    row = w.tc.get("/api/v1/cplugs/localplug", headers=w.owner_headers).json()
    assert row["enabled"] is True and row["state"] == "active"

    (plug / "main.py").write_text(
        (plug / "main.py").read_text(encoding="utf-8") + "\n# local edit\n",
        encoding="utf-8",
    )
    assert run_install(str(plug), client=w.owner_cli, assume_yes=True, enable=True, as_json=True) == 0
    capsys.readouterr()
    row_after = w.tc.get("/api/v1/cplugs/localplug", headers=w.owner_headers).json()
    assert row_after["enabled"] is True and row_after["state"] == "active"

    plug_no_en = tmp_path / "noenableplug"
    assert cli_main(["new", "noenableplug", "--template", "no-code", "--dir", str(plug_no_en)]) == 0
    assert run_install(str(plug_no_en), client=w.owner_cli, assume_yes=True, enable=False) == 0
    assert w.tc.get("/api/v1/cplugs/noenableplug", headers=w.owner_headers).json()["enabled"] is False

    plug_noreason = tmp_path / "noreasonplug"
    assert cli_main(["new", "noreasonplug", "--template", "python", "--dir", str(plug_noreason)]) == 0
    toml_text = (plug_noreason / "carnivore.toml").read_text(encoding="utf-8")
    (plug_noreason / "carnivore.toml").write_text(toml_text.split("[permissions.reasons]")[0], encoding="utf-8")
    assert run_install(str(plug_noreason), client=w.owner_cli, assume_yes=True) == 1
    assert "reason_missing" in capsys.readouterr().err


def test_run_install_github_contract(
    live_app: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    w = live_app
    from src.core.dev_tools import git_guard

    monkeypatch.setattr(git_guard, "git_available", lambda: True)
    monkeypatch.setattr(sideload_git, "check_url", lambda url: url)
    monkeypatch.setattr(sideload_git, "ALLOWED_PROTOCOLS", ("https", "ssh", "file"))

    bare, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("init", "-q", "-b", "main", str(work))
    assert cli_main(["new", "ghplug", "--template", "python", "--dir", str(work / "ghplug")]) == 0
    for p in (work / "ghplug").iterdir():
        shutil.move(str(p), str(work / p.name))
    (work / "ghplug").rmdir()
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "init", cwd=work)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)

    calls_before = len(w.owner_cli.calls)
    assert run_install(f"file://{bare}", mode="github", client=w.owner_cli, assume_yes=False) == 2
    assert len(w.owner_cli.calls) == calls_before
    capsys.readouterr()

    assert w.tc.put("/api/v1/cplug-owner/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200
    assert w.tc.put("/api/v1/cplug-owner/sideload/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200

    monkeypatch.setattr(
        "src.plugins.cli.install_publish.detect_source",
        lambda _s, mode="auto": ("github", {"url": f"file://{bare}", "ref": "nonexistent-ref"}),
    )
    assert run_install("acme/ghplug@nonexistent-ref", mode="github", client=w.owner_cli, assume_yes=True) == 1
    assert "install failed" in capsys.readouterr().err

    monkeypatch.setattr(
        "src.plugins.cli.install_publish.detect_source",
        lambda _s, mode="auto": ("github", {"url": f"file://{bare}", "ref": "main"}),
    )
    assert run_install("acme/ghplug@main", mode="github", client=w.owner_cli, assume_yes=True, as_json=True) == 0
    res_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res_doc["id"] == "ghplug"
    assert w.tc.get("/api/v1/cplugs/ghplug", headers=w.owner_headers).json()["enabled"] is True


@pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)
def test_run_install_warez_contract(live_app: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = live_app
    commit = "e" * 40
    toml_text = (
        'schema = 2\nid = "clock"\nname = "Clock"\nversion = "1.0.0"\nkind = "plugin"\n'
        'description = "Tells time."\nauthor = "acme"\nlicense = "MIT"\nmin_app_version = "1.12.20"\n'
        'tier = "catalog"\ndefault_enabled = false\n'
        '[run]\ncmd = ["python3", "main.py"]\nmode = "rpc"\n'
        '[permissions]\nwrite = ["notify"]\n'
        '[permissions.reasons]\nnotify = "Notifies when timer completes."\n'
        '[[mcp.tools]]\nname = "clock_now"\ndescription = "Get time."\ngate = "read"\n'
        'inputSchema = { type = "object" }\n'
    )
    files = {"carnivore.toml": toml_text.encode(), "main.py": b"print('ok')\n"}
    pkg = build_skill(tmp_path, publisher="acme", name="clock", files=files, commit=commit, folder=kinds.archive_folder(kinds.KIND_CPLUG))
    serve_archive(w.served, pkg.tar_bytes, commit=commit)
    item = skill_item(
        "clock",
        "acme",
        pkg.digest,
        kind=kinds.KIND_CPLUG,
        repo=FIXTURE_REPO,
        commit=commit,
        path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/acme/clock",
    )

    bad_toml = toml_text.replace('id = "clock"', 'id = "noreasonclock"').replace('min_app_version = "1.12.20"', 'min_app_version = "99.99.99"')
    bad_files = {"carnivore.toml": bad_toml.encode(), "main.py": b"print('ok')\n"}
    bad_pkg = build_skill(
        tmp_path / "badpkg",
        publisher="acme",
        name="noreasonclock",
        files=bad_files,
        commit="f" * 40,
        folder=kinds.archive_folder(kinds.KIND_CPLUG),
    )
    serve_archive(w.served, bad_pkg.tar_bytes, commit="f" * 40)
    bad_item = skill_item(
        "noreasonclock",
        "acme",
        bad_pkg.digest,
        kind=kinds.KIND_CPLUG,
        repo=FIXTURE_REPO,
        commit="f" * 40,
        path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/acme/noreasonclock",
    )

    publish_index(tmp_path, w.served, index_keypair=w.index_kp, publisher_keypair=w.publisher_kp, items=[item, bad_item], serial=1)

    assert run_install("acme/missing", client=w.owner_cli, assume_yes=True) == 1
    assert "preview failed (404)" in capsys.readouterr().err

    assert run_install("acme/clock", client=w.owner_cli, assume_yes=True, as_json=True) == 0
    res_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res_doc["name"] == "clock" and res_doc["kind"] == "cplug"
    install_req = next(body for m, p, body, _sc in w.owner_cli.calls if m == "POST" and p == "/api/v1/catalog/install")
    assert install_req is not None
    consent = install_req["consent"]
    assert consent["scripts"] is True
    assert consent["cplug_accepted"] is True
    assert isinstance(consent["digest"], str) and len(consent["digest"]) == 64
    assert isinstance(consent["body_sha"], str) and len(consent["body_sha"]) == 64
    assert isinstance(consent["cplug_facts_sha"], str) and len(consent["cplug_facts_sha"]) == 64

    assert w.tc.get("/api/v1/cplugs/clock", headers=w.owner_headers).json()["enabled"] is True

    assert run_install("acme/noreasonclock", client=w.owner_cli, assume_yes=True) == 1
    assert "enable failed (409)" in capsys.readouterr().err


def test_run_publish_contract_v2_v1_and_failures(live_app: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = live_app

    bad = tmp_path / "bad-plug"
    bad.mkdir()
    assert run_publish(bad, client=w.owner_cli, assume_yes=True) == 1
    assert "check error:" in capsys.readouterr().err

    good = tmp_path / "pubplug"
    assert cli_main(["new", "pubplug", "--template", "python", "--dir", str(good)]) == 0

    assert run_publish(good, client=w.owner_cli, assume_yes=True, as_json=True) == 0
    out_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out_doc["submission_id"] == SUBMISSION_ID

    sub_reqs = [req for req in w.sent_hosted if req.method == "POST" and req.url.path.endswith("/submissions")]
    assert len(sub_reqs) == 1
    assert sub_reqs[0].headers.get("Authorization") == "Bearer HELD-ACCESS-SECRET"
    body = json.loads(sub_reqs[0].content.decode("utf-8"))
    assert body["kind"] == "cplug"
    assert body["schema"] == 2
    assert body["name"] == "pubplug"
    assert body["version"] == "0.1.0"
    files = {f["path"]: base64.b64decode(f["content_base64"]).decode("utf-8") for f in body["files"]}
    assert "carnivore.toml" in files and "main.py" in files
    assert not any(p.startswith("tests/") for p in files)

    assert run_publish(good, client=w.key_cli, assume_yes=True) == 1
    assert "403" in capsys.readouterr().err

    sym = tmp_path / "pubplug-link"
    sym.symlink_to(good)
    r_sym = w.tc.post("/api/v1/cplug-owner/publish", json={"path": str(sym), "dry_run": True}, headers=w.owner_headers)
    assert r_sym.status_code == 422 and r_sym.json()["detail"]["code"] == "source_missing"

    before_count = len(w.sent_hosted)
    assert run_publish(good, version="0.2.0", client=w.owner_cli, assume_yes=True) == 1
    assert "refusal:" in capsys.readouterr().err
    assert len([r for r in w.sent_hosted[before_count:] if r.method == "POST"]) == 0

    v2_json_copy = tmp_path / "warezjsonpub"
    v2_json_copy.mkdir()
    (v2_json_copy / "carnivore.json").write_text(
        json.dumps({
            "schema": 2,
            "id": "warezjsonpub",
            "name": "Warez JSON Pub",
            "version": "0.1.0",
            "kind": "plugin",
            "description": "v2 JSON publish test",
            "author": "alice",
            "license": "MIT",
            "tier": "local",
            "default_enabled": False,
            "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        }),
        encoding="utf-8",
    )
    (v2_json_copy / "main.py").write_text(
        "import asyncio\n"
        "from cplug_sdk import Plugin\n"
        "plugin = Plugin()\n"
        "if __name__ == '__main__':\n"
        "    asyncio.run(plugin.serve())\n",
        encoding="utf-8",
    )
    assert run_publish(v2_json_copy, client=w.owner_cli, assume_yes=True, as_json=True) == 0
    v2_req = [req for req in w.sent_hosted if req.method == "POST" and req.url.path.endswith("/submissions")][-1]
    v2_body = json.loads(v2_req.content.decode("utf-8"))
    assert v2_body["kind"] == "cplug" and v2_body["schema"] == 2
    v2_files = {f["path"]: json.loads(base64.b64decode(f["content_base64"]).decode("utf-8")) for f in v2_body["files"] if f["path"].endswith(".json")}
    assert v2_files["carnivore.json"]["tier"] == "catalog"
    assert v2_files["carnivore.json"]["default_enabled"] is False

    w.hosted_routes[("POST", "/submissions")] = (409, {"code": "name_taken", "detail": "already taken"})
    assert run_publish(good, client=w.owner_cli, assume_yes=True) == 1
    assert "409" in capsys.readouterr().err

    catalog_publish_routes.clear_handle_cache(id(w.app))
    w.hosted_routes[("GET", "/me")] = (200, {"provider": "github", "login": "alice", "handle": "", "registered": False})
    before_empty = len([r for r in w.sent_hosted if r.method == "POST"])
    assert run_publish(good, client=w.owner_cli, assume_yes=True) == 2
    assert "claimed publisher handle" in capsys.readouterr().err
    assert len([r for r in w.sent_hosted if r.method == "POST"]) == before_empty


@pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)
def test_run_install_warez_v2_toml_and_json_contract(
    live_app: SimpleNamespace,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    w = live_app
    assert w.tc.put("/api/v1/cplug-owner/switch", json={"enabled": True}, headers=w.owner_headers).status_code == 200

    toml_src = tmp_path / "wareztoml"
    assert cli_main(["new", "wareztoml", "--template", "python", "--dir", str(toml_src)]) == 0
    shutil.rmtree(toml_src / "tests")
    toml_files = {
        p.relative_to(toml_src).as_posix(): p.read_bytes()
        for p in sorted(toml_src.rglob("*"))
        if p.is_file()
    }
    toml_commit = "a" * 40
    toml_pkg = build_skill(
        tmp_path / "pkg_toml",
        publisher="acme",
        name="wareztoml",
        files=toml_files,
        commit=toml_commit,
        folder=kinds.archive_folder(kinds.KIND_CPLUG),
    )
    serve_archive(w.served, toml_pkg.tar_bytes, commit=toml_commit)
    toml_item = skill_item(
        "wareztoml",
        "acme",
        toml_pkg.digest,
        kind=kinds.KIND_CPLUG,
        repo=FIXTURE_REPO,
        commit=toml_commit,
        path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/acme/wareztoml",
    )

    v2_json_doc = {
        "schema": 2,
        "id": "warezjson",
        "name": "Warez JSON",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Schema 2 JSON Warez plugin.",
        "author": "acme",
        "license": "MIT",
        "min_app_version": "1.16.0",
        "tier": "catalog",
        "default_enabled": False,
        "run": {"cmd": ["python3", "main.py"], "mode": "rpc"},
        "permissions": {
            "write": ["notify"],
            "reasons": {"notify": "Send notifications."},
        },
        "mcp": {
            "tools": [
                {
                    "name": "warezjson_ping",
                    "description": "Return pong.",
                    "gate": "read",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            ]
        },
    }
    v2_json_bytes = (json.dumps(v2_json_doc, indent=2) + "\n").encode("utf-8")
    v2_main_bytes = (
        "import asyncio\n"
        "from cplug_sdk import Plugin\n"
        "plugin = Plugin()\n"
        "@plugin.tool('warezjson_ping', 'Return pong.', {'type': 'object', 'properties': {}, 'additionalProperties': False}, gate='read')\n"
        "async def ping(_args, _caller):\n"
        "    return 'pong'\n"
        "if __name__ == '__main__':\n"
        "    asyncio.run(plugin.serve())\n"
    ).encode("utf-8")
    json_commit = "b" * 40
    json_pkg = build_skill(
        tmp_path / "pkg_json",
        publisher="acme",
        name="warezjson",
        files={"carnivore.json": v2_json_bytes, "main.py": v2_main_bytes},
        commit=json_commit,
        folder=kinds.archive_folder(kinds.KIND_CPLUG),
    )
    serve_archive(w.served, json_pkg.tar_bytes, commit=json_commit)
    json_item = skill_item(
        "warezjson",
        "acme",
        json_pkg.digest,
        kind=kinds.KIND_CPLUG,
        repo=FIXTURE_REPO,
        commit=json_commit,
        path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/acme/warezjson",
    )

    now_dt = datetime.now(timezone.utc)
    w.clock._at = now_dt.timestamp() + 60.0
    publish_index(
        tmp_path,
        w.served,
        index_keypair=w.index_kp,
        publisher_keypair=w.publisher_kp,
        items=[toml_item, json_item],
        serial=1,
        generated_at=now_dt,
    )

    for name, expected_bytes in (
        ("wareztoml", toml_files["carnivore.toml"]),
        ("warezjson", v2_json_bytes),
    ):
        r_contents = w.tc.get(f"/api/v1/catalog/contents/acme/{name}", headers=w.owner_headers)
        assert r_contents.status_code == 200, r_contents.text
        assert r_contents.json()["body"] == expected_bytes.decode("utf-8")

        calls_before = len(w.owner_cli.calls)
        assert run_install(f"acme/{name}", mode="warez", client=w.owner_cli, assume_yes=True, enable=True, as_json=True) == 0
        out_doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out_doc["name"] == name and out_doc["kind"] == "cplug"

        install_req = next(
            body
            for m, p, body, _sc in w.owner_cli.calls[calls_before:]
            if m == "POST" and p == "/api/v1/catalog/install"
        )
        assert install_req is not None
        consent = install_req["consent"]
        assert consent["cplug_accepted"] is True
        assert consent["body_sha"] == hashlib.sha256(expected_bytes).hexdigest()

        row = w.tc.get(f"/api/v1/cplugs/{name}", headers=w.owner_headers).json()
        assert row["enabled"] is True and row["state"] == "active"


def _make_cplug_tar(tmp_path: Path, members: Dict[str, bytes], *, name: str = "pkg.tar.gz") -> Path:
    prefix = "repo-1111/cplugs/acme/myplug/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, data in members.items():
            info = tarfile.TarInfo(f"{prefix}{rel}")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    out = tmp_path / name
    out.write_bytes(buf.getvalue())
    return out


def test_cplug_v2_archive_validation_and_staging_matrix(tmp_path: Path) -> None:
    toml_ok = b'schema = 2\nid = "myplug"\nname = "My Plug"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "a"\n'
    json_v2 = json.dumps({"schema": 2, "id": "myplug", "name": "My Plug", "version": "1.0.0", "kind": "plugin", "description": "d", "author": "a"}).encode()
    json_v1 = json.dumps({"kind": "cplug", "id": "acme/myplug", "name": "My Plug", "version": "1.0.0"}).encode()
    cplug_v1 = json.dumps({"schema": 1, "id": "myplug", "name": "My Plug", "version": "1.0.0"}).encode()

    for idx, files in enumerate((
        {"carnivore.toml": toml_ok, "main.py": b"print(1)\n"},
        {"carnivore.json": json_v2, "main.py": b"print(1)\n"},
        {"cplug.json": cplug_v1, "carnivore.json": json_v1, "main.py": b"print(1)\n"},
    )):
        tar_p = _make_cplug_tar(tmp_path, files, name=f"ok_{idx}.tar.gz")
        validated = validate_archive(tar_p, publisher="acme", name="myplug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/myplug")
        assert validated.digest
        dest = tmp_path / f"staged_ok_{idx}"
        staged = stage_archive(tar_p, dest, publisher="acme", name="myplug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/myplug")
        assert staged.digest == validated.digest
        assert check_manifest(kinds.KIND_CPLUG, dest, expected_id="myplug") is None

    for idx, files in enumerate((
        {"carnivore.json": json_v1, "main.py": b"print(1)\n"},
        {"carnivore.toml": toml_ok, "cplug.json": cplug_v1},
        {"carnivore.toml": toml_ok, "carnivore.json": json_v1},
        {"cplug.json": cplug_v1, "carnivore.json": json_v2},
        {"carnivore.toml": toml_ok, "sub/carnivore.toml": toml_ok},
        {"carnivore.json": json_v2, "sub/carnivore.json": json_v2},
    )):
        tar_p = _make_cplug_tar(tmp_path, files, name=f"bad_{idx}.tar.gz")
        with pytest.raises(ArchiveRefused) as caught:
            validate_archive(tar_p, publisher="acme", name="myplug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/myplug")
        assert caught.value.code == ARCHIVE_INVALID
        folder = tmp_path / f"dir_bad_{idx}"
        folder.mkdir()
        for rel, data in files.items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(data)
        if not any("/" in rel for rel in files):
            assert check_manifest(kinds.KIND_CPLUG, folder, expected_id="myplug") is not None

    for idx, bad_toml in enumerate((b"schema = [invalid", b'schema = 1\nid = "myplug"\n')):
        tar_p = _make_cplug_tar(tmp_path, {"carnivore.toml": bad_toml}, name=f"bad_toml_{idx}.tar.gz")
        with pytest.raises(ArchiveRefused) as caught:
            stage_archive(tar_p, tmp_path / f"staged_bad_toml_{idx}", publisher="acme", name="myplug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/myplug")
        assert caught.value.code == ARCHIVE_INVALID


def test_oversized_dual_manifest_bypass_refused_across_all_gates(tmp_path: Path) -> None:
    from src.plugins.host import install_gates, sideload, sideload_kind
    from src.plugins.sdk.manifest_v2 import ManifestV2Error, has_v2_manifest, load_manifest_v2

    decoy_cplug = json.dumps({
        "schema": 1,
        "id": "smug",
        "name": "Harmless Decoy",
        "description": "Decoy",
        "version": "1.0.0",
        "entry": "decoy.py",
        "tools": [],
        "permissions": {"app": []},
    }).encode("utf-8")
    v2_core = json.dumps({
        "schema": 2,
        "id": "smug",
        "name": "Smuggled Runtime",
        "version": "1.0.0",
        "kind": "plugin",
        "description": "Hidden payload",
        "author": "acme",
        "run": {"cmd": ["python3", "real.py"], "mode": "rpc"},
    }).encode("utf-8")
    pad_len = max(1, (1024 * 1024 + 512) - len(v2_core))
    oversized_v2_json = v2_core + (b" " * pad_len)
    assert len(oversized_v2_json) > 1024 * 1024

    files = {
        "cplug.json": decoy_cplug,
        "carnivore.json": oversized_v2_json,
        "decoy.py": b"print('decoy')\n",
        "real.py": b"print('real')\n",
    }
    tar_p = tmp_path / "smug.tar.gz"
    prefix = "repo-1111/cplugs/acme/smug/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, data in files.items():
            info = tarfile.TarInfo(f"{prefix}{rel}")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    tar_p.write_bytes(buf.getvalue())

    with pytest.raises(ArchiveRefused) as caught_val:
        validate_archive(tar_p, publisher="acme", name="smug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/smug")
    assert caught_val.value.code == ARCHIVE_INVALID

    with pytest.raises(ArchiveRefused) as caught_stage:
        stage_archive(tar_p, tmp_path / "staged_smug", publisher="acme", name="smug", kind=kinds.KIND_CPLUG, src_path="cplugs/acme/smug")
    assert caught_stage.value.code == ARCHIVE_INVALID

    folder = tmp_path / "disk_smug"
    folder.mkdir()
    for rel, data in files.items():
        (folder / rel).write_bytes(data)

    assert check_manifest(kinds.KIND_CPLUG, folder, expected_id="smug") is not None
    assert has_v2_manifest(folder) is True
    with pytest.raises(ManifestV2Error):
        load_manifest_v2(folder)
    with pytest.raises(install_gates.CplugGateRefusal) as caught_gate:
        install_gates.evaluate("acme/smug", folder)
    assert caught_gate.value.code == install_gates.MANIFEST_INVALID
    with pytest.raises(sideload.SideloadRefused) as caught_side:
        sideload_kind.detect(folder)
    assert caught_side.value.code in ("manifest_invalid", "kind_ambiguous")

    mid_folder = tmp_path / "disk_mid"
    mid_folder.mkdir()
    mid_v2_json = v2_core + (b" " * (70 * 1024))
    (mid_folder / "cplug.json").write_bytes(decoy_cplug)
    (mid_folder / "carnivore.json").write_bytes(mid_v2_json)
    with pytest.raises(sideload.SideloadRefused) as caught_mid:
        sideload_kind.detect(mid_folder)
    assert caught_mid.value.code == "kind_ambiguous"
