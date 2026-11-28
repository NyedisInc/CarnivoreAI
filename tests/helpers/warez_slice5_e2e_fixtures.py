
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import (
    catalog_contents_routes,
    catalog_install_routes,
    catalog_installed_routes,
    catalog_required_routes,
    catalog_routes,
    themes_routes,
)
from src.api.auth import require_auth
from src.core.catalog import archive_client
from src.core.catalog import client as catalog_client
from src.core.catalog.index_refresher import IndexRefresher
from src.core.catalog.minisign import parse_public_key
from src.core.catalog.services import build_catalog_services
from src.core.composition import build_services
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills import kinds
from src.core.skills.digest import digest_directory
from src.core.ui_preferences_store import UiPreferencesStore
from src.models.catalog_statement import release_statement
from src.plugins.host import owner_switch, routes as host_routes, runtime as host_runtime, sidecar_boot, sidecar_registry
from tests.helpers import submissions_harness as sh
from tests.helpers.catalog_app import StateOnlySettings
from tests.helpers.catalog_fixture import revocation_entry, signature_block, sign_bytes
from tests.helpers.catalog_surface import FIXTURE_REPO, FrozenClock, fixture_trust_root, keypairs
from tests.helpers.hosted_catalog_fake import lambda_modules
from tests.helpers.minisign_keys import Keypair, minisign_binary
from tests.helpers.static_http import StaticServer, self_signed_cert, serve_directory

REPO_ROOT = Path(__file__).resolve().parents[2]
DARWIN_SANDBOX = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None
INDEX_PATH = "v1/index.json"
CATALOG_SLUG = "NyedisInc/CarnivoreAI-Catalog"
DEFAULT_MIT_LICENSE = (
    "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy "
    "of this software to deal in the Software without restriction.\n"
)


def git_run(cwd: Path, *args: str, env_extra: Optional[Mapping[str, str]] = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if env_extra:
        env.update(env_extra)
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True)
    return (done.stdout or "").strip()


def make_tarball_bytes(
    files: Mapping[str, bytes],
    *,
    repo: str = FIXTURE_REPO,
    commit: str,
    publisher: str,
    name: str,
    folder: str = "plugins",
    exec_paths: Sequence[str] = (),
) -> bytes:
    prefix = f"{repo.split('/')[1]}-{commit}/{folder}/{publisher}/{name}/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, body in sorted(files.items()):
            info = tarfile.TarInfo(f"{prefix}{relpath}")
            info.mode = 0o755 if relpath in exec_paths else 0o644
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def make_zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for relpath, body in sorted(files.items()):
            zf.writestr(relpath, body)
    return buf.getvalue()


def write_plugin_tree(folder: Path, files: Mapping[str, bytes], *, exec_paths: Sequence[str] = ()) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for relpath, body in files.items():
        target = folder / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        os.chmod(target, 0o755 if relpath in exec_paths else 0o644)
    return folder


def make_run_plugin_files(
    plugin_id: str = "harborclock",
    *,
    version: str = "1.0.0",
    author: str = "harbor",
    description: str = "Provides a read clock tool and live declarative widget.",
    permissions: Optional[Dict[str, Any]] = None,
    services: Optional[Dict[str, Any]] = None,
    events: Optional[Dict[str, Any]] = None,
    run_cmd: Sequence[str] = ("python3", "main.py"),
    trust: Optional[str] = None,
    extra_files: Optional[Dict[str, bytes]] = None,
) -> Dict[str, bytes]:
    doc: Dict[str, Any] = {
        "schema": 2,
        "id": plugin_id,
        "name": plugin_id.replace("_", " ").title(),
        "version": version,
        "kind": "plugin",
        "description": description,
        "author": author,
        "license": "MIT",
        "min_app_version": "1.16.0",
        "api_version": 1,
        "tier": "catalog",
        "default_enabled": False,
        "run": {"cmd": list(run_cmd), "mode": "rpc"},
        "ui": {
            "widget": {
                "title": f"{plugin_id} Widget",
                "sizes": ["medium", "large"],
                "mode": "ui_doc",
            }
        },
        "mcp": {
            "tools": [
                {
                    "name": f"{plugin_id}_ping",
                    "description": "Return a deterministic status string without side effects.",
                    "gate": "read",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            ]
        },
    }
    if permissions is not None:
        doc["permissions"] = permissions
    if services is not None:
        doc["services"] = services
    if events is not None:
        doc["events"] = events
    if trust is not None:
        doc["trust"] = trust

    main_py = textwrap.dedent(
        f"""\
        \"\"\"Minimal v2 RPC plugin entrypoint for {plugin_id}.\"\"\"

        from __future__ import annotations

        from typing import Any, Dict

        from cplug_sdk import Plugin

        plugin = Plugin()


        @plugin.ui("widget")
        async def render_widget(params: Dict[str, Any]) -> Dict[str, Any]:
            theme = str(params.get("theme", "dark"))
            size = str(params.get("size", "medium"))
            return {{
                "schema": 2,
                "root": {{
                    "type": "column",
                    "children": [
                        {{"type": "text", "value": f"{plugin_id} {{theme}} {{size}}"}},
                    ],
                }},
            }}


        @plugin.tool(
            "{plugin_id}_ping",
            "Return a deterministic status string without side effects.",
            {{"type": "object", "properties": {{}}, "additionalProperties": False}},
            gate="read",
        )
        async def ping(args: Dict[str, Any], caller: Any) -> str:
            return "pong:{version}"
        """
    ).encode("utf-8")

    files: Dict[str, bytes] = {
        "carnivore.json": (json.dumps(doc, indent=2) + "\n").encode("utf-8"),
        "main.py": main_py,
        "LICENSE.md": DEFAULT_MIT_LICENSE.encode("utf-8"),
    }
    if extra_files:
        files.update(extra_files)
    return files


def make_tier0_plugin_files(
    plugin_id: str = "tierzero",
    *,
    version: str = "1.0.0",
    author: str = "harbor",
    description: str = "Declarative Tier 0 widget and CLI harness without executable code.",
    permissions: Optional[Dict[str, Any]] = None,
    services: Optional[Dict[str, Any]] = None,
    events: Optional[Dict[str, Any]] = None,
) -> Dict[str, bytes]:
    lines = [
        "schema = 2",
        f'id = "{plugin_id}"',
        f'name = "{plugin_id.title()}"',
        f'version = "{version}"',
        'kind = "plugin"',
        f'description = "{description}"',
        f'author = "{author}"',
        'license = "MIT"',
        'min_app_version = "1.16.0"',
        "api_version = 1",
        'tier = "catalog"',
        "default_enabled = false",
        'harnesses = ["harnesses/mockcli.toml"]',
        "",
        "[ui.widget]",
        f'title = "{plugin_id.title()}"',
        'sizes = ["small", "medium"]',
        'ui_file = "widget.ui.json"',
    ]
    if permissions:
        lines.append("")
        lines.append("[permissions]")
        for key in ("read", "write", "secrets"):
            if key in permissions:
                lines.append(f"{key} = {json.dumps(permissions[key])}")
        if "network" in permissions:
            lines.append(f"network = {json.dumps(permissions['network'])}")
        if "reasons" in permissions:
            lines.append("")
            lines.append("[permissions.reasons]")
            for rk, rv in permissions["reasons"].items():
                lines.append(f'{json.dumps(rk)} = {json.dumps(rv)}')
    if services:
        lines.append("")
        lines.append("[services]")
        if "consumes" in services:
            lines.append(f"consumes = {json.dumps(services['consumes'])}")
        for prov in services.get("provides", ()):
            lines.append("[[services.provides]]")
            lines.append(f"name = {json.dumps(prov['name'])}")
            lines.append(f"methods = {json.dumps(prov['methods'])}")
    if events:
        lines.append("")
        lines.append("[events]")
        for ek in ("on", "emit"):
            if ek in events:
                lines.append(f"{ek} = {json.dumps(events[ek])}")

    widget_doc = {
        "schema": 2,
        "root": {"type": "column", "children": [{"type": "text", "value": f"{plugin_id} v{version}"}]},
    }
    harness_toml = (
        f'id = "mock{plugin_id}"\nversion = "1.0"\n\n'
        '[[rules]]\nid = "working"\nstate = "working"\n'
        'contains = ["thinking"]\nregex = ["thinking\\\\.\\\\.\\\\."]\n'
    )
    return {
        "carnivore.toml": ("\n".join(lines) + "\n").encode("utf-8"),
        "widget.ui.json": (json.dumps(widget_doc, indent=2) + "\n").encode("utf-8"),
        "harnesses/mockcli.toml": harness_toml.encode("utf-8"),
        "LICENSE.md": DEFAULT_MIT_LICENSE.encode("utf-8"),
    }


@dataclass(frozen=True)
class GitRepoBundle:

    bare_dir: Path
    work_dir: Path
    commit_sha: str
    tag: str
    minisig_pub: str
    provenance_sig: str
    allowed_signers: str
    minisig_keypair: Optional[Keypair]


def create_signed_git_plugin_repo(
    root: Path,
    *,
    files: Mapping[str, bytes],
    tag: str = "v1.0.0",
    repo_slug: str = "",
    sign_ssh: bool = True,
    sign_minisig: bool = True,
    embed_minisig_files: bool = True,
    keypair: Optional[Keypair] = None,
    exec_paths: Sequence[str] = (),
) -> GitRepoBundle:
    work = root / "work"
    write_plugin_tree(work, files, exec_paths=exec_paths)

    minisig_pub = ""
    kp = keypair
    if sign_minisig:
        if minisign_binary() is None:
            raise RuntimeError("minisign binary unavailable")
        if kp is None:
            from tests.helpers.minisign_keys import generate_keypair

            kdir = root / "minisign_kp"
            kdir.mkdir(parents=True, exist_ok=True)
            kp = generate_keypair(kdir)
        minisig_pub = kp.public_key_text.strip()
        if embed_minisig_files:
            manifest_name = "carnivore.toml" if (work / "carnivore.toml").is_file() else "carnivore.json"
            sig_text = sign_bytes(root, kp, (work / manifest_name).read_bytes(), f"prov-{tag}")
            (work / f"{manifest_name}.minisig").write_text(sig_text, encoding="utf-8")
            (work / "PUBLISHER.pub").write_text(minisig_pub + "\n", encoding="utf-8")

    git_run(work, "init", "-b", "main")
    git_run(work, "config", "user.name", "Harbor Release")
    git_run(work, "config", "user.email", "harbor@example.com")
    git_run(work, "add", "-A")
    git_run(work, "commit", "-m", f"Release {tag}")

    allowed_signers = ""
    if sign_ssh:
        ssh_dir = root / "ssh_signing"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        priv = ssh_dir / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(priv)],
            check=True,
            capture_output=True,
        )
        pub_line = (ssh_dir / "id_ed25519.pub").read_text(encoding="utf-8").strip()
        allowed_signers = f'harbor@example.com namespaces="git" {pub_line}\n'
        git_run(work, "config", "gpg.format", "ssh")
        git_run(work, "config", "user.signingkey", str(priv))
        git_run(work, "tag", "-s", tag, "-m", f"Signed release {tag}")
    else:
        git_run(work, "tag", "-a", tag, "-m", f"Annotated release {tag}")

    commit_sha = git_run(work, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    provenance_sig = ""
    if sign_minisig and kp is not None and repo_slug:
        provenance_sig = sign_bytes(root, kp, f"{repo_slug}@{tag}:{commit_sha}".encode("utf-8"), f"psig-{tag}")
    bare = root / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(work), str(bare)], check=True, capture_output=True)
    return GitRepoBundle(
        bare_dir=bare,
        work_dir=work,
        commit_sha=commit_sha,
        tag=tag,
        minisig_pub=minisig_pub,
        provenance_sig=provenance_sig,
        allowed_signers=allowed_signers,
        minisig_keypair=kp,
    )


class HostedGateApiAdapter:

    def __init__(
        self,
        api: Any,
        *,
        gate_token: str,
        publish_token: str,
        owner: str = "e2e-runner",
    ) -> None:
        self._api = api
        self._gate_token = gate_token
        self._publish_token = publish_token
        self.owner = owner

    def _call(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        bearer: str,
        query: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        raw_body = json.dumps(body) if body is not None else None
        resp = self._api.app.handler(sh.event(method, path, raw_body, bearer, query=query))
        parsed = sh.body_of(resp)
        if resp["statusCode"] >= 400:
            raise RuntimeError(f"{method} {path} -> {resp['statusCode']}: {parsed}")
        return parsed

    def pin(self, submission_id: str, **kwargs: Any) -> Dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/submissions/{submission_id}/pin",
            {"owner": self.owner, **kwargs},
            bearer=self._gate_token,
        )

    def review_budget(self, submission_id: str) -> bool:
        resp = self._api.app.handler(
            sh.event(
                "POST",
                f"/v1/submissions/{submission_id}/review-budget",
                json.dumps({"owner": self.owner}),
                self._gate_token,
            )
        )
        return resp["statusCode"] == 200

    def revocations(self) -> List[Dict[str, Any]]:
        out = self._call(
            "GET",
            "/v1/submissions",
            bearer=self._publish_token,
            query={"status": "revoked", "revocation_state": "pending"},
        )
        return list(out.get("items") or out.get("submissions") or [])

    def claim_row(self, submission_id: str) -> Dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/submissions/{submission_id}/claim",
            {"owner": self.owner},
            bearer=self._publish_token,
        )

    def release(self, submission_id: str, reason: str) -> Dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/submissions/{submission_id}/release",
            {"owner": self.owner, "reason": reason},
            bearer=self._publish_token,
        )

    def facts(self, submission_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/v1/submissions/{submission_id}/facts", bearer=self._publish_token)

    def revocation_published(self, submission_id: str, merge_sha: str = "") -> Dict[str, Any]:
        body: Dict[str, Any] = {"owner": self.owner}
        if merge_sha:
            body["merge_sha"] = merge_sha
        return self._call(
            "POST",
            f"/v1/submissions/{submission_id}/revocation-published",
            body,
            bearer=self._publish_token,
        )


def make_catalog_checkout(
    tmp_path: Path,
    *,
    publisher_handle: str,
    publisher_kp: Keypair,
    repo_slug: str = CATALOG_SLUG,
) -> Path:
    checkout = tmp_path / "catalog_checkout"
    checkout.mkdir(parents=True, exist_ok=True)
    git_run(checkout, "init", "-b", "main")
    git_run(checkout, "config", "user.name", "Catalog Builder")
    git_run(checkout, "config", "user.email", "builder@example.com")
    (checkout / "tools").symlink_to(REPO_ROOT / "hosted" / "catalog_index" / "tools")
    (checkout / "catalog.yml").write_text(
        f"repo: {repo_slug}\nmin_serial: 1\nstaleness_days: 30\n"
        "review_model: google/gemini-2.5-flash-lite\nreview_max_chars: 40000\n",
        encoding="utf-8",
    )
    pub_line = publisher_kp.public_key_text.splitlines()[-1].strip()
    pub_key_id = parse_public_key(publisher_kp.public_key_text).key_id
    (checkout / "releases").mkdir(parents=True, exist_ok=True)
    (checkout / "publishers").mkdir(parents=True, exist_ok=True)
    (checkout / "publishers" / f"{publisher_handle}.json").write_text(
        json.dumps(
            {
                "handle": publisher_handle,
                "github_login": publisher_handle,
                "keys": [
                    {
                        "key_id": pub_key_id,
                        "alg": "Ed25519",
                        "pub": pub_line,
                        "added": "2026-11-25",
                        "status": "active",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (checkout / ".gitignore").write_text("tools\n", encoding="utf-8")
    git_run(checkout, "add", "-A")
    git_run(checkout, "commit", "-m", "seed catalog checkout")
    return checkout


def publish_cplug_to_checkout(
    checkout: Path,
    tmp_path: Path,
    *,
    handle: str,
    name: str,
    version: str,
    files: Mapping[str, bytes],
    publisher_kp: Keypair,
    served_root: Path,
    provenance: Optional[Dict[str, Any]] = None,
    review: Optional[Dict[str, Any]] = None,
    repo_slug: str = CATALOG_SLUG,
    exec_paths: Sequence[str] = (),
) -> Tuple[str, str, Dict[str, Any]]:
    plugin_dir = checkout / "plugins" / handle / name
    twin_dir = checkout / "cplugs" / handle / name
    for target_dir in (plugin_dir, twin_dir):
        if target_dir.exists():
            shutil.rmtree(target_dir)
        write_plugin_tree(target_dir, files, exec_paths=exec_paths)
    git_run(checkout, "add", "-A")
    git_run(checkout, "commit", "-m", f"stage {handle}/{name} {version}")
    commit = git_run(checkout, "rev-parse", "HEAD")
    digest, _ = digest_directory(plugin_dir)

    rel_path = f"plugins/{handle}/{name}"
    stmt = release_statement(
        kind=kinds.KIND_CPLUG,
        publisher=handle,
        name=name,
        version=version,
        repo=repo_slug,
        path=rel_path,
        commit=commit,
        digest=digest,
    )
    sig_blk = signature_block(tmp_path, publisher_kp, stmt, f"rel-{name}-{version}")
    rel_dir = checkout / "releases" / handle / name
    rel_dir.mkdir(parents=True, exist_ok=True)
    rel_payload: Dict[str, Any] = {
        "statement": stmt.decode("utf-8"),
        "sig": sig_blk,
        "commit": commit,
        "digest": digest,
    }
    if provenance is not None:
        rel_payload["provenance"] = provenance
    (rel_dir / f"{version}.json").write_text(json.dumps(rel_payload, indent=2) + "\n", encoding="utf-8")
    if twin_dir.exists():
        shutil.rmtree(twin_dir)
    git_run(checkout, "add", "-A")
    git_run(checkout, "commit", "-m", f"release {handle}/{name} {version}")

    tar_bytes = make_tarball_bytes(
        files,
        repo=repo_slug,
        commit=commit,
        publisher=handle,
        name=name,
        folder="plugins",
        exec_paths=exec_paths,
    )
    target = served_root / repo_slug / "tar.gz" / commit
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(tar_bytes)
    return commit, digest, {"review": review, "commit": commit, "digest": digest}


def build_and_publish_checkout_index(
    checkout: Path,
    tmp_path: Path,
    served_root: Path,
    *,
    index_kp: Keypair,
    publisher_kp: Keypair,
    serial: int,
    reviews_by_key: Optional[Mapping[Tuple[str, str], Dict[str, Any]]] = None,
    revocations_list: Optional[Sequence[Dict[str, str]]] = None,
    repo_slug: str = CATALOG_SLUG,
) -> Dict[str, Any]:
    tools_dir = str((REPO_ROOT / "hosted" / "catalog_index" / "tools").resolve())
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from index_builder.assemble import _version_entry, assemble
    from index_builder.publishers import load_publishers
    from index_builder.releases import find_release_files, verify_release

    publishers = load_publishers(checkout)
    verified = [
        verify_release(checkout, p, publishers=publishers, repo_slug=repo_slug)
        for p in find_release_files(checkout)
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    built = assemble(
        checkout,
        publishers=publishers,
        releases=verified,
        repo_slug=repo_slug,
        serial=serial,
        generated_at=stamp,
    )
    doc = dict(built.document)
    if reviews_by_key:
        for item in doc["items"]:
            new_versions = []
            for ver in item["versions"]:
                r_obj = next(
                    r for r in verified
                    if f"{r.handle}/{r.name}" == item["id"] and r.version == ver["v"]
                )
                rev = reviews_by_key.get((item["id"], ver["v"]))
                new_versions.append(_version_entry(r_obj, repo_slug, rev))
            item["versions"] = new_versions

    if revocations_list:
        doc["revocations"] = {
            "keys": [],
            "versions": [
                revocation_entry(
                    tmp_path,
                    kind="version",
                    subject=f"{entry['item']}@{entry['version']}",
                    since=entry["since"],
                    keypair=publisher_kp,
                )
                for entry in revocations_list
            ],
        }
    else:
        doc["revocations"] = {"keys": [], "versions": []}

    raw_bytes = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    minisig_text = sign_bytes(tmp_path, index_kp, raw_bytes, f"idx-{serial}")
    index_file = served_root / INDEX_PATH
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_bytes(raw_bytes)
    (index_file.parent / f"{index_file.name}.minisig").write_text(minisig_text, encoding="utf-8")
    return doc


@dataclass
class E2EClientContext:

    client: TestClient
    server: StaticServer
    state: Path
    services: Any
    clock: FrozenClock
    api: Any
    admin_token: str
    submitter_token: str
    gate_token: str
    publish_token: str
    gate_adapter: HostedGateApiAdapter
    index_kp: Keypair
    publisher_kp: Keypair
    served_root: Path
    checkout: Path

    def host(self) -> host_runtime.Host:
        return host_runtime.host_for(self.client.app)

    def runtime(self) -> sidecar_boot.SidecarRuntime:
        return self.client.app.state.sidecar_runtime


@contextlib.contextmanager
def open_e2e_bridge(
    tmp_path: Path,
    *,
    publisher_handle: str = "harbor",
    submitter_id: str = sh.OTHER_ID,
) -> Iterator[E2EClientContext]:
    prev_gates = os.environ.get("GATES_REQUIRED")
    os.environ["GATES_REQUIRED"] = "1"
    try:
        with lambda_modules(sh.JWT_TEST_SECRET) as api:
            yield from _open_bridge_with_api(
                api, tmp_path, publisher_handle=publisher_handle, submitter_id=submitter_id
            )
    finally:
        if prev_gates is None:
            os.environ.pop("GATES_REQUIRED", None)
        else:
            os.environ["GATES_REQUIRED"] = prev_gates


def _open_bridge_with_api(
    api: Any,
    tmp_path: Path,
    *,
    publisher_handle: str,
    submitter_id: str,
) -> Iterator[E2EClientContext]:
    sh.reset(api)
    api.http_api.ADMIN_GITHUB_USER_ID = sh.ADMIN_ID
    api.dynamodb.Table(api.store.USERS_TABLE).seed(
        {"user_id": sh.ADMIN_ID},
        {"login": "catalog-admin", "created_at": 1_700_000_000, "auth_method": "passkey"},
    )
    api.dynamodb.Table(api.submissions.SUBMISSIONS_TABLE)
    admin_token = sh.token(api, sh.ADMIN_ID, "catalog-admin")
    submitter_token = sh.token(api, submitter_id, publisher_handle)

    gate_mint = api.bot_tokens.mint(
        "e2e-gate",
        sh.ADMIN_ID,
        [api.bot_tokens.SCOPE_GATE, api.bot_tokens.SCOPE_VERIFY],
        amr="passkey",
    )
    pub_mint = api.bot_tokens.mint(
        "e2e-pub",
        sh.ADMIN_ID,
        api.bot_tokens.PUBLISH_SCOPES,
        amr="passkey",
    )
    gate_adapter = HostedGateApiAdapter(
        api,
        gate_token=gate_mint["token"],
        publish_token=pub_mint["token"],
    )

    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    trust = fixture_trust_root(index_kp, publisher_kp)
    served_root = tmp_path / "served"
    served_root.mkdir(parents=True, exist_ok=True)
    checkout = make_catalog_checkout(tmp_path, publisher_handle=publisher_handle, publisher_kp=publisher_kp)
    build_and_publish_checkout_index(
        checkout, tmp_path, served_root, index_kp=index_kp, publisher_kp=publisher_kp, serial=1
    )

    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert = self_signed_cert(tls_dir)
    if cert is None:
        raise RuntimeError("self_signed_cert returned None")

    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")
    owner_switch.write(state, True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")
    prefs = UiPreferencesStore(lambda: config_path)
    roots = LiveInstallRoots(settings_reader=StateOnlySettings(state))
    clock = FrozenClock(at=datetime.now(timezone.utc).timestamp())

    def open_db():
        return connect(db_path_for(state))

    with serve_directory(served_root, tls_cert=cert) as server:
        index_url = f"{server.base_url}/{INDEX_PATH}"
        prev_base = archive_client.CODELOAD_BASE_URL
        archive_client.CODELOAD_BASE_URL = server.base_url
        try:
            catalog = build_catalog_services(
                index_url=lambda: index_url,
                api_base_url=lambda: "https://catalog.invalid/api/v1",
                clock=clock,
                open_db=open_db,
                trust_root=trust,
            )
            services = build_services(
                clock=clock,
                install_roots=roots,
                catalog=catalog,
                settings_reader=StateOnlySettings(state),
                ui_preferences=prefs,
            )

            @contextlib.asynccontextmanager
            async def lifespan(fastapi_app: FastAPI):
                await catalog_client.init(verify=str(cert[0]))
                rt = sidecar_boot.SidecarRuntime(
                    host,
                    fastapi_app,
                    asyncio.get_running_loop(),
                    env_safe=lambda: False,
                    app_version="1.16.0",
                )
                fastapi_app.state.sidecar_runtime = rt
                await rt.start()
                refresher.after_pass = rt.index.sync
                refresher.hourly_while = rt.index.third_party_enabled
                try:
                    yield
                finally:
                    await rt.stop()
                    sidecar_registry.install(None)
                    await catalog_client.shutdown()

            app = FastAPI(lifespan=lifespan)
            for rtr in (
                catalog_contents_routes.router,
                catalog_required_routes.router,
                catalog_routes.router,
                catalog_install_routes.router,
                catalog_installed_routes.router,
                themes_routes.router,
                host_routes.router,
            ):
                app.include_router(rtr, prefix="/api/v1")
            app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
            app.state.services = services
            app.state.ui_preferences_store = prefs
            refresher = IndexRefresher(catalog.index_cache, services=services)
            catalog.index_cache.after_index_sync = refresher.notify_after_pass
            app.state.catalog_index_refresher = refresher
            host = host_runtime.Host(state, app=app, publish=lambda _topic: None)
            app.state.cplugs_host = host

            with TestClient(app) as client:
                yield E2EClientContext(
                    client=client,
                    server=server,
                    state=state,
                    services=services,
                    clock=clock,
                    api=api,
                    admin_token=admin_token,
                    submitter_token=submitter_token,
                    gate_token=gate_mint["token"],
                    publish_token=pub_mint["token"],
                    gate_adapter=gate_adapter,
                    index_kp=index_kp,
                    publisher_kp=publisher_kp,
                    served_root=served_root,
                    checkout=checkout,
                )
        finally:
            archive_client.CODELOAD_BASE_URL = prev_base


def b64_members(files: Mapping[str, bytes]) -> List[Dict[str, str]]:
    return [
        {"path": path, "content_base64": base64.b64encode(body).decode("ascii")}
        for path, body in sorted(files.items())
    ]


def build_12_gate_report(
    *,
    submission_id: str,
    handle: str,
    name: str,
    version: str,
    folder_digest: str,
    static_results: Sequence[Any],
    gate10_verdict: str,
    gate10_code: str,
    gate10_findings: Sequence[Dict[str, Any]],
    gate11_result: Any,
    review_doc: Dict[str, Any],
    outcome: str,
) -> Dict[str, Any]:
    by_n: Dict[int, Dict[str, Any]] = {}
    for res in static_results:
        by_n[int(res.n)] = res.to_json()
    by_n[10] = {
        "n": 10,
        "id": "ai_review",
        "verdict": gate10_verdict,
        "code": gate10_code,
        "findings": list(gate10_findings),
    }
    by_n[11] = gate11_result.to_json()
    if 12 not in by_n:
        by_n[12] = {"n": 12, "id": "grade", "verdict": "pass", "code": "ok", "findings": []}
    gates = [by_n[n] for n in range(1, 13)]
    return {
        "schema": "carnivore.warez.gate-report/1",
        "app_sha": "a" * 40,
        "outcome": outcome,
        "submission_id": submission_id,
        "kind": "cplug",
        "handle": handle,
        "name": name,
        "version": version,
        "folder_digest": folder_digest,
        "digest": folder_digest,
        "gates": gates,
        "review": review_doc,
    }


def make_runner_for_review_json(
    catalog_checkout: Path,
    *,
    handle: str,
    name: str,
    version: str,
    digest: str,
    raw_model_json: str,
    extra_review_fields: Optional[Mapping[str, Any]] = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    tools_dir = str((catalog_checkout / "tools").resolve())
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from index_builder.review import parse_review

    verdict, summary, warnings = parse_review(raw_model_json)

    def _runner(command: Sequence[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        repo_root = Path(command[command.index("--repo-root") + 1])
        artifact = repo_root / "reviews" / handle / name / f"{version}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        doc: Dict[str, Any] = {
            "status": "reviewed",
            "verdict": verdict,
            "summary": summary,
            "warnings": warnings,
            "digest": digest,
            "model": "test-deterministic-reviewer",
            "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if extra_review_fields:
            doc.update(extra_review_fields)
        artifact.write_text(json.dumps(doc), encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    return _runner
