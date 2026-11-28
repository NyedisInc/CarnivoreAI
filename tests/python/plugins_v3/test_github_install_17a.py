
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from src.core import relay_keychain
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills.kinds import KIND_CPLUG
from src.core.skills.ledger import InstallLedger
from src.plugins.host import (
    developer_mode,
    github_install_routes,
    identity,
    owner_switch,
    runtime,
    secret_store,
    sidecar_boot,
    sidecar_registry,
    sideload,
    sideload_git,
    sideload_routes,
)
from tests.python.api_keys.conftest import bearer, key_store, owner_jwt  # noqa: F401

OWNER_REPO = "acme/ghdemo"
CANONICAL_URL = f"https://github.com/{OWNER_REPO}.git"


def _init_bare_repo(tmp_path: Path, files: Dict[str, str]) -> Path:
    work = tmp_path / f"work-{len(list(tmp_path.iterdir()))}"
    bare = tmp_path / f"bare-{len(list(tmp_path.iterdir()))}.git"
    work.mkdir(parents=True)
    for rel, content in files.items():
        p = work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=work, check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


class _MemKeychain:
    def __init__(self) -> None:
        self.saved: Dict[tuple[str, str], str] = {}

    def read(self, service: str, account: str) -> Optional[str]:
        return self.saved.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.saved[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.saved.pop((service, account), None) is not None


def _consent_body(sheet: Dict[str, Any]) -> Dict[str, Any]:
    ticks = [p["name"] for p in sheet["permissions"] if p.get("needs_tick")]
    return {
        "digest": sheet["digest"],
        "body_sha": sheet["body_sha"],
        "grants_sha": sheet["grants_sha"],
        "ticks": ticks,
    }


@pytest.fixture
def gh_world(tmp_path: Path, owner_jwt, key_store, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    from src.main import app

    @contextlib.asynccontextmanager
    async def _noop_lifespan(_app: Any):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")

    mem_kc = _MemKeychain()
    monkeypatch.setattr(secret_store, "_Login", lambda: mem_kc)

    monkeypatch.setattr(developer_mode, "is_on", lambda: False)

    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    project_dir = tmp_path / "projects" / "demo-proj"
    (project_dir / ".claude" / "skills").mkdir(parents=True)
    settings_reader = SimpleNamespace(state_dir=lambda: state)
    roots = LiveInstallRoots(settings_reader=settings_reader)

    catalog_snap = SimpleNamespace(items=[
        SimpleNamespace(
            id="verifiedpub/takenplugin",
            kind=KIND_CPLUG,
            publisher="verifiedpub",
            name="takenplugin",
        )
    ])
    fake_services = SimpleNamespace(
        catalog=SimpleNamespace(index_cache=SimpleNamespace(current=lambda: catalog_snap)),
        install_roots=roots,
        settings_reader=settings_reader,
    )

    published: list[str] = []
    host = runtime.Host(state, app)
    monkeypatch.setattr(host, "publish", lambda topic: published.append(topic))
    loop = asyncio.new_event_loop()
    rt = sidecar_boot.SidecarRuntime(host, app, loop, env_safe=lambda: False, app_version="9.9.9")
    app.state.sidecar_runtime = rt
    app.state.cplugs_host = host
    app.state.services = fake_services

    monkeypatch.setattr(
        github_install_routes,
        "resolve_project_path",
        lambda p, **_kw: str(Path(p).resolve()),
    )

    _row, api_secret = key_store.create("script")
    with TestClient(app) as tc:
        try:
            yield SimpleNamespace(
                client=tc,
                state=state,
                owner=bearer(owner_jwt),
                api_key=bearer(api_secret),
                rt=rt,
                keychain=mem_kc,
                project_dir=project_dir,
                fake_home=fake_home,
                app=app,
                monkeypatch=monkeypatch,
            )
        finally:
            if tc.portal is not None:
                tc.portal.call(rt.supervisor.shutdown)
            for attr in ("sidecar_runtime", "cplugs_host", "services"):
                if hasattr(app.state, attr):
                    delattr(app.state, attr)
            sidecar_registry.install(None)
            loop.close()


def _wire_bare_github(monkeypatch: pytest.MonkeyPatch, bare_repo: Path) -> None:
    monkeypatch.setattr(sideload_git, "ALLOWED_PROTOCOLS", ("https", "file"))
    orig_config = sideload_git._config
    monkeypatch.setattr(
        sideload_git,
        "_config",
        lambda: [*orig_config(), "-c", f"url.file://{bare_repo}/.insteadOf={CANONICAL_URL}"],
    )


def test_parse_github_source_validation() -> None:
    assert sideload_git.parse_github_source("acme/demo") == ("acme", "demo", "https://github.com/acme/demo.git", None)
    assert sideload_git.parse_github_source("acme/demo@v1.2.0") == ("acme", "demo", "https://github.com/acme/demo.git", "v1.2.0")
    assert sideload_git.parse_github_source("https://github.com/acme/demo.git", "main") == (
        "acme", "demo", "https://github.com/acme/demo.git", "main"
    )
    for bad in (
        "https://gitlab.com/acme/demo",
        "http://github.com/acme/demo",
        "file:///tmp/demo",
        "git@github.com:acme/demo.git",
        "https://user:tok@github.com/acme/demo",
        "https://github.com/acme/demo/extra",
        "-uhack/repo",
        "justonepart",
    ):
        with pytest.raises(sideload_git.SideloadRefused):
            sideload_git.parse_github_source(bad)


def test_github_preview_and_install_outside_dev_mode_with_inline_secrets_and_runtime(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghwidget"
name = "GH Widget"
kind = "plugin"
description = "Widget from GitHub"
author = "Acme"
license = "MIT"
version = "0.2.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
app = ["sessions.read"]
secrets = [{ name = "api_token", label = "GitHub Token" }]

[[permissions.network]]
host = "api.github.com"
methods = ["GET"]
reason = "sync repo status"
auth = { secret = "api_token", header = "Authorization", scheme = "Bearer" }

[permissions.reasons]
"sessions.read" = "reads session list"
""",
            "main.py": "print('ready')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)

    r_fence = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.api_key,
    )
    assert r_fence.status_code == 403

    r_prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    )
    assert r_prev.status_code == 200, r_prev.text
    prev = r_prev.json()
    assert prev["id"] == "ghwidget"
    assert prev["kind"] == "cplug"
    assert prev["trust_tier"] == "unverified_github"
    assert prev["trust_badge"] == "Unverified GitHub Repo"
    assert prev["unverified"] is True
    assert prev["code_sha256"]
    assert prev["supported_scopes"] == ["global"]
    assert prev["secrets"][0]["name"] == "api_token"
    assert prev["runtime_active"] is False
    assert prev["source"]["owner"] == "acme"
    assert prev["source"]["repo"] == "ghdemo"

    r_no_consent = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    )
    assert r_no_consent.status_code == 422

    secret_val = "ghp_ExampleSecretToken12345"
    r_inst = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "activate_runtime": True,
            "secrets": {"api_token": secret_val},
            "consent": _consent_body(prev["consent_sheet"]),
        },
        headers=gh_world.owner,
    )
    assert r_inst.status_code == 200, r_inst.text
    inst = r_inst.json()
    assert secret_val not in r_inst.text
    assert inst["trust_tier"] == "unverified_github"
    assert inst["trust_badge"] == "Unverified GitHub Repo"
    assert inst["unverified"] is True
    assert inst["runtime_active"] is True
    assert inst["secrets_status"] == {"api_token": {"present": True, "needs_reentry": False}}
    assert owner_switch.read(gh_world.state) is True
    assert (f"carnivore-cplug-{inst['install_key']}", "api_token") in gh_world.keychain.saved
    assert gh_world.keychain.saved[(f"carnivore-cplug-{inst['install_key']}", "api_token")] == secret_val

    r_list = gh_world.client.get("/api/v1/cplugs", headers=gh_world.owner)
    assert r_list.status_code == 200
    row = next(item for item in r_list.json()["cplugs"] if item["id"] == "ghwidget")
    assert row["kind"] == "cplug"
    assert row["trust_tier"] == "unverified_github"
    assert row["trust_badge"] == "Unverified GitHub Repo"
    assert row["unverified"] is True
    assert row["scope"] == "global"
    assert row["runtime_paused"] is False
    assert row["secrets_status"] == {"api_token": {"present": True, "needs_reentry": False}}
    assert row["git_source"]["url"] == CANONICAL_URL

    new_secret = "ghp_UpdatedSecretToken98765"
    r_put = gh_world.client.put(
        "/api/v1/cplugs/ghwidget",
        json={"revision": row["revision"], "secrets": {"api_token": new_secret}, "activate_runtime": True},
        headers=gh_world.owner,
    )
    assert r_put.status_code == 200, r_put.text
    assert new_secret not in r_put.text
    assert gh_world.keychain.saved[(f"carnivore-cplug-{inst['install_key']}", "api_token")] == new_secret


def test_github_rejects_warez_hijack_and_env_safe_mode(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "takenplugin"
name = "Hijack"
kind = "plugin"
description = "Tries to claim Warez catalog ID"
author = "Evil"
license = "MIT"
version = "1.0.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
            "main.py": "print('hi')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    r_hijack = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    )
    assert r_hijack.status_code == 409, r_hijack.text
    assert r_hijack.json()["detail"]["code"] == "catalog_id_hijack"

    gh_world.monkeypatch.setattr(gh_world.rt, "_env_safe", lambda: True)
    r_safe = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO, "activate_runtime": True},
        headers=gh_world.owner,
    )
    assert r_safe.status_code == 409
    assert r_safe.json()["detail"]["code"] == "safe_mode_forced"


def test_github_agent_plugin_project_scope_and_listing(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            ".claude-plugin/plugin.json": json.dumps({
                "name": "gh-agent-mod",
                "version": "1.0.0",
                "description": "Agent plugin from GitHub",
            }),
            "commands/hello.md": "# hello\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    r_prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO, "scope": "project", "project_path": str(gh_world.project_dir)},
        headers=gh_world.owner,
    )
    assert r_prev.status_code == 200, r_prev.text
    prev = r_prev.json()
    assert prev["kind"] == "agent-plugin"
    assert prev["supported_scopes"] == ["global", "project"]
    assert prev["scope"] == "project"

    r_inst = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "scope": "project",
            "project_path": str(gh_world.project_dir),
            "consent": {
                "digest": prev["consent_sheet"]["digest"],
                "body_sha": prev["consent_sheet"]["body_sha"],
            },
        },
        headers=gh_world.owner,
    )
    assert r_inst.status_code == 200, r_inst.text
    assert (gh_world.project_dir / ".claude" / "skills" / "gh-agent-mod" / ".claude-plugin" / "plugin.json").is_file()

    r_list = gh_world.client.get("/api/v1/cplugs?include_agent_plugins=true", headers=gh_world.owner)
    assert r_list.status_code == 200
    ap_row = next(r for r in r_list.json()["cplugs"] if r["id"] == "gh-agent-mod")
    assert ap_row["kind"] == "agent-plugin"
    assert ap_row["scope"] == "project"
    assert ap_row["trust_tier"] == "unverified_github"


def test_github_install_does_not_pollute_sideload_items_or_stop_on_dev_mode_off(
    tmp_path: Path, gh_world: SimpleNamespace
) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghisolated"
name = "GH Isolated"
kind = "plugin"
description = "Runs outside dev mode"
author = "Acme"
license = "MIT"
version = "0.1.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
            "main.py": "print('ok')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    ).json()
    r_inst = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO, "enable": True, "consent": _consent_body(prev["consent_sheet"])},
        headers=gh_world.owner,
    )
    assert r_inst.status_code == 200, r_inst.text
    assert "ghisolated" not in sideload.items(gh_world.state)

    r_sl = gh_world.client.get("/api/v1/cplug-owner/sideload", headers=gh_world.owner)
    assert r_sl.status_code == 200
    assert [it["id"] for it in r_sl.json()["items"]] == []

    stopped: list[str] = []
    orig_disable = gh_world.rt.supervisor.disable

    async def _spy_disable(name: str, reason: str = "", **kw: Any) -> Any:
        stopped.append(name)
        return await orig_disable(name, reason, **kw)

    gh_world.monkeypatch.setattr(gh_world.rt.supervisor, "disable", _spy_disable)

    r_del = gh_world.client.delete("/api/v1/cplug-owner/sideload?name=ghisolated", headers=gh_world.owner)
    assert r_del.status_code == 404
    assert r_del.json()["detail"]["code"] == "sideload_unknown"
    assert "ghisolated" not in stopped

    gh_world.client.portal.call(sideload_routes.stop_on_developer_mode_off, gh_world.app)
    assert "ghisolated" not in stopped
    r_list = gh_world.client.get("/api/v1/cplugs", headers=gh_world.owner)
    assert any(item["id"] == "ghisolated" and item["enabled"] is True for item in r_list.json()["cplugs"])


def test_github_install_enable_false_skips_runtime_activation(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghdisabled"
name = "GH Disabled"
kind = "plugin"
description = "Install disabled"
author = "Acme"
license = "MIT"
version = "0.1.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
            "main.py": "print('ok')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    ).json()
    r_inst = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "enable": False,
            "activate_runtime": True,
            "consent": _consent_body(prev["consent_sheet"]),
        },
        headers=gh_world.owner,
    )
    assert r_inst.status_code == 200, r_inst.text
    assert r_inst.json()["enabled"] is False
    assert owner_switch.read(gh_world.state) is False
    r_row = gh_world.client.get("/api/v1/cplugs/ghdisabled", headers=gh_world.owner)
    assert r_row.status_code == 200
    assert r_row.json()["enabled"] is False


def test_github_agent_plugin_multi_project_unique_install_ids(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            ".claude-plugin/plugin.json": json.dumps({
                "name": "gh-multi-proj",
                "version": "1.0.0",
                "description": "Multi project agent plugin",
            }),
            "commands/hello.md": "# hello\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    proj_a = tmp_path / "projects" / "projA"
    proj_b = tmp_path / "projects" / "projB"
    (proj_a / ".claude" / "skills").mkdir(parents=True)
    (proj_b / ".claude" / "skills").mkdir(parents=True)

    prev_a = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO, "scope": "project", "project_path": str(proj_a)},
        headers=gh_world.owner,
    ).json()
    consent = {"digest": prev_a["consent_sheet"]["digest"], "body_sha": prev_a["consent_sheet"]["body_sha"]}

    r_a = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO, "scope": "project", "project_path": str(proj_a), "consent": consent},
        headers=gh_world.owner,
    )
    assert r_a.status_code == 200, r_a.text

    r_b = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO, "scope": "project", "project_path": str(proj_b), "consent": consent},
        headers=gh_world.owner,
    )
    assert r_b.status_code == 200, r_b.text
    assert r_a.json()["install_id"] != r_b.json()["install_id"]

    conn = connect(db_path_for(gh_world.state), create=False)
    try:
        rows = [r for r in InstallLedger(conn).list() if r.item_id == "github/gh-multi-proj"]
    finally:
        conn.close()
    assert len(rows) == 2
    assert {r.project_path for r in rows} == {str(proj_a.resolve()), str(proj_b.resolve())}


def test_github_install_and_put_cplug_atomic_secret_rollback(tmp_path: Path, gh_world: SimpleNamespace) -> None:
    bare = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghroll"
name = "GH Rollback"
kind = "plugin"
description = "Rollback test"
author = "Acme"
license = "MIT"
version = "0.1.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"

[permissions]
secrets = [
  { name = "api_token", label = "API Token" },
  { name = "secondary_token", label = "Secondary Token" },
]

[[permissions.network]]
host = "api.github.com"
methods = ["GET"]
reason = "api access"
auth = { secret = "api_token", header = "Authorization", scheme = "Bearer" }

[[permissions.network]]
host = "uploads.github.com"
methods = ["POST"]
reason = "upload access"
auth = { secret = "secondary_token", header = "Authorization", scheme = "Bearer" }
""",
            "main.py": "print('ok')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare)
    prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    ).json()

    r_bad = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "secrets": {
                "api_token": "ghp_GoodSecretToken123456789012345678",
                "undeclared_secret": "ghp_BadSecretToken123456789012345678",
            },
            "consent": _consent_body(prev["consent_sheet"]),
        },
        headers=gh_world.owner,
    )
    assert r_bad.status_code == 404
    assert r_bad.json()["detail"]["code"] == "secret_unknown"
    assert identity.lookup(gh_world.state, "ghroll") is None
    assert not (gh_world.state / "plugins" / "ghroll").exists()
    assert not gh_world.keychain.saved
    assert "ghroll" not in sideload_git.records(gh_world.state)

    orig_write = gh_world.keychain.write

    def _fail_second(service: str, account: str, secret: str) -> None:
        if account == "secondary_token":
            raise relay_keychain.KeychainWriteError("denied")
        orig_write(service, account, secret)

    gh_world.monkeypatch.setattr(gh_world.keychain, "write", _fail_second)
    r_kc_fail = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "secrets": {
                "api_token": "ghp_GoodSecretToken123456789012345678",
                "secondary_token": "ghp_FailSecretToken123456789012345678",
            },
            "consent": _consent_body(prev["consent_sheet"]),
        },
        headers=gh_world.owner,
    )
    assert r_kc_fail.status_code == 503
    assert r_kc_fail.json()["detail"]["code"] == "keychain_refused"
    assert identity.lookup(gh_world.state, "ghroll") is None
    assert not (gh_world.state / "plugins" / "ghroll").exists()
    assert not gh_world.keychain.saved
    assert "ghroll" not in sideload_git.records(gh_world.state)
    conn = connect(db_path_for(gh_world.state), create=False)
    try:
        assert InstallLedger(conn).find("github/ghroll", "global", "") is None
    finally:
        conn.close()

    gh_world.monkeypatch.setattr(gh_world.keychain, "write", orig_write)
    r_ok = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={
            "source": OWNER_REPO,
            "secrets": {"api_token": "ghp_InitialSecretToken1234567890123456"},
            "consent": _consent_body(prev["consent_sheet"]),
        },
        headers=gh_world.owner,
    )
    assert r_ok.status_code == 200, r_ok.text
    row_before = gh_world.client.get("/api/v1/cplugs/ghroll", headers=gh_world.owner).json()
    rev_before = row_before["revision"]
    assert row_before["enabled"] is True

    gh_world.monkeypatch.setattr(gh_world.keychain, "write", _fail_second)
    r_put_fail = gh_world.client.put(
        "/api/v1/cplugs/ghroll",
        json={
            "revision": rev_before,
            "enabled": False,
            "secrets": {
                "api_token": "ghp_NewSecretToken12345678901234567890",
                "secondary_token": "ghp_FailSecretToken123456789012345678",
            },
        },
        headers=gh_world.owner,
    )
    assert r_put_fail.status_code == 503
    assert r_put_fail.json()["detail"]["code"] == "keychain_refused"
    row_after = gh_world.client.get("/api/v1/cplugs/ghroll", headers=gh_world.owner).json()
    assert row_after["revision"] == rev_before
    assert row_after["enabled"] is True
    assert gh_world.keychain.saved[(f"carnivore-cplug-{r_ok.json()['install_key']}", "api_token")] == "ghp_InitialSecretToken1234567890123456"


def test_github_install_post_reload_failure_rolls_back_sidecar_registry(
    tmp_path: Path, gh_world: SimpleNamespace
) -> None:
    bare_v1 = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghsw"
name = "GH Switch Rollback"
kind = "plugin"
description = "Switch rollback test"
author = "Acme"
license = "MIT"
version = "0.1.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
            "main.py": "print('v1')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare_v1)
    prev = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    ).json()

    host = gh_world.app.state.cplugs_host
    orig_switch = host._switch_sidecar

    async def _fail_switch(_defn: Any, _enabled: bool) -> None:
        raise RuntimeError("switch_sidecar_failed")

    gh_world.monkeypatch.setattr(host, "_switch_sidecar", _fail_switch)
    with pytest.raises(RuntimeError, match="switch_sidecar_failed"):
        gh_world.client.post(
            "/api/v1/cplug-owner/github/install",
            json={"source": OWNER_REPO, "enable": True, "consent": _consent_body(prev["consent_sheet"])},
            headers=gh_world.owner,
        )
    assert runtime.find("ghsw") is None
    assert identity.lookup(gh_world.state, "ghsw") is None
    assert not (gh_world.state / "plugins" / "ghsw").exists()

    gh_world.monkeypatch.setattr(host, "_switch_sidecar", orig_switch)
    r_v1 = gh_world.client.post(
        "/api/v1/cplug-owner/github/install",
        json={"source": OWNER_REPO, "enable": True, "consent": _consent_body(prev["consent_sheet"])},
        headers=gh_world.owner,
    )
    assert r_v1.status_code == 200, r_v1.text
    assert runtime.find("ghsw").manifest.version == "0.1.0"

    bare_v2 = _init_bare_repo(
        tmp_path,
        {
            "carnivore.toml": """schema = 2
id = "ghsw"
name = "GH Switch Rollback"
kind = "plugin"
description = "Switch rollback test"
author = "Acme"
license = "MIT"
version = "0.2.0"

[run]
cmd = ["python3", "main.py"]
mode = "rpc"
""",
            "main.py": "print('v2')\n",
        },
    )
    _wire_bare_github(gh_world.monkeypatch, bare_v2)
    prev_v2 = gh_world.client.post(
        "/api/v1/cplug-owner/github/preview",
        json={"source": OWNER_REPO},
        headers=gh_world.owner,
    ).json()

    gh_world.monkeypatch.setattr(host, "_switch_sidecar", _fail_switch)
    with pytest.raises(RuntimeError, match="switch_sidecar_failed"):
        gh_world.client.post(
            "/api/v1/cplug-owner/github/install",
            json={"source": OWNER_REPO, "enable": True, "consent": _consent_body(prev_v2["consent_sheet"])},
            headers=gh_world.owner,
        )
    restored = runtime.find("ghsw")
    assert restored is not None
    assert restored.manifest.version == "0.1.0"
    assert restored.code_root.exists()
