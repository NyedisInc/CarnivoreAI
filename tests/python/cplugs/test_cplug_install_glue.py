
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import catalog_cplug_gates
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills import kinds
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.cplugs.host import identity, install_gates, mcp, sidecar_boot, sidecar_registry
from src.cplugs.host import state as owner_state
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_surface import (
    FIXTURE_REPO, build_skill, fixture_trust_root, keypairs, publish_index, serve_archive, skill_item)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)

PUBLISHER = "acme"
NAME = "clock"
ITEM_ID = f"{PUBLISHER}/{NAME}"
COMMIT = "e" * 40
GLOBAL = {"item_id": ITEM_ID, "scope": "global"}
TOOL_TEXT = "Return the current time as an ISO string. Reads the system clock and nothing else."


def cplug_files(name: str = NAME, *, extra: dict = None) -> dict:
    cplug = {"schema": 1, "id": name, "name": "Clock", "description": "Tells the time.", "version": "1.0.0", "entry": "main.py",
             "tools": [{"name": "clock_now", "description": TOOL_TEXT, "gate": "read", "inputSchema": {"type": "object", "properties": {}}}],
             "permissions": {"app": ["notify"]}}
    side = {"kind": "cplug", "id": ITEM_ID, "name": "Clock", "version": "1.0.0", "api_version": 1, "min_app_version": "1.12.20",
            "author": PUBLISHER, "license": "MIT", "tier": "catalog", "scope": ["global"], "icon": "plug", "default_enabled": False,
            "permissions": [{"name": "notify", "reason": "tells you when the time is up"}], "owns": {}, "data": []}
    files = {"cplug.json": json.dumps(cplug).encode(), "carnivore.json": json.dumps(side).encode(), "main.py": b"print('tick')\n"}
    files.update(extra or {})
    return files


def publish(tmp_path: Path, files: dict, *, exec_paths=(), keys=None):
    served = tmp_path / "served"
    served.mkdir(exist_ok=True)
    index_kp, publisher_kp, _stranger = keys or keypairs(tmp_path / "keys")
    package = build_skill(tmp_path, publisher=PUBLISHER, name=NAME, files=files, commit=COMMIT, folder=kinds.archive_folder(kinds.KIND_CPLUG),
                          exec_paths=exec_paths)
    serve_archive(served, package.tar_bytes, commit=COMMIT)
    item = skill_item(NAME, PUBLISHER, package.digest, kind=kinds.KIND_CPLUG, repo=FIXTURE_REPO, commit=COMMIT,
                      path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/{PUBLISHER}/{NAME}")
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[item], serial=1)
    return fixture_trust_root(index_kp, publisher_kp), package


def live_roots(settings):
    return LiveInstallRoots(settings_reader=settings)


def attach_runtime(app, state: Path):
    host = SimpleNamespace(state_dir=state, publish=lambda topic: None, install_key=lambda name: name)
    loop = asyncio.new_event_loop()
    rt = sidecar_boot.SidecarRuntime(host, app, loop, env_safe=lambda: False, app_version="9.9.9")
    app.state.sidecar_runtime = rt
    return rt


def refusal_code(response) -> str:
    detail = response.json().get("detail") if response.status_code == 409 else None
    return detail.get("code", "") if isinstance(detail, dict) else ""


def test_preview_then_install_leaves_a_disabled_registered_plugin_then_uninstall_keeps_the_name(tmp_path):
    trust, package = publish(tmp_path, cplug_files())
    state = tmp_path / "state"
    (tmp_path / "served").mkdir(exist_ok=True)
    with catalog_app(tmp_path, tmp_path / "served", trust_root=trust, roots_factory=live_roots) as app:
        rt = attach_runtime(app.client.app, state)
        preview = app.client.post("/catalog/install/preview", json=GLOBAL)
        assert preview.status_code in (200, 409), preview.text
        sheet = preview.json()
        sheet = sheet["detail"] if isinstance(sheet.get("detail"), dict) else sheet
        facts = sheet["cplug_facts"]
        assert facts["tools"][0]["description"] == TOOL_TEXT
        assert [p["name"] for p in facts["permissions"]] == ["notify"] and facts["permissions"][0]["reason"]
        assert sheet["cplug_facts_sha"]
        assert not (state / "cplug-code" / NAME).exists() and ledger_rows(app) == []
        assert identity.lookup(state, NAME) is None

        consent = {"digest": package.digest, "body_sha": sheet["body_sha"], "scripts": True, "cplug_accepted": True,
                   "cplug_facts_sha": "0" * 64}
        bad = app.client.raw_post("/catalog/install", json={**GLOBAL, "consent": consent})
        assert refusal_code(bad) == install_gates.FACTS_CHANGED, bad.text
        unticked = app.client.raw_post("/catalog/install", json={**GLOBAL, "consent": {**consent, "cplug_accepted": False}})
        assert refusal_code(unticked) == install_gates.NOT_ACCEPTED
        assert ledger_rows(app) == [] and identity.lookup(state, NAME) is None

        good = app.client.raw_post("/catalog/install", json={**GLOBAL, "consent": {**consent, "cplug_facts_sha": sheet["cplug_facts_sha"]}})
        assert good.status_code == 200, good.text

        (row,) = ledger_rows(app)
        assert row.kind == kinds.KIND_CPLUG and row.item_id == ITEM_ID
        root = state / "cplug-code" / NAME
        assert (root / "cplug.json").is_file() and (root / "main.py").is_file()
        (skill_target,) = app.services.install_roots.targets_for(kinds.KIND_SKILL, SCOPE_GLOBAL, None)[:1]
        assert skill_target.leaf_dir != state / "cplug-code"

        definition = sidecar_registry.find(NAME)
        assert definition is not None and definition.code_root == root
        owned = owner_state.get(state, definition.manifest)
        assert owned.enabled is False and tuple(owned.grants) == ()
        assert rt.supervisor.process(NAME) is None
        assert mcp.spec_of("clock_now") is None
        record = identity.lookup(state, NAME)
        assert record is not None and record.catalog_id == ITEM_ID

        data = identity.data_dir(state, record.uuid)
        data.mkdir(parents=True, exist_ok=True)
        (data / "note.txt").write_text("kept")
        gone = app.client.delete(f"/catalog/installed/{row.install_id}")
        assert gone.status_code == 200, gone.text
        assert not root.exists() and ledger_rows(app) == []
        assert sidecar_registry.find(NAME) is None
        assert identity.lookup(state, NAME) is not None
        stranger = SimpleNamespace(id=f"evil/{NAME}")
        with pytest.raises(HTTPException) as caught:
            catalog_cplug_gates.reserve_install(SimpleNamespace(app=app.client.app), stranger)
        assert caught.value.detail["code"] == "name_taken"


def test_uninstall_with_nothing_left_to_purge_frees_the_name_and_lists_no_removed_row(tmp_path):
    trust, package = publish(tmp_path, cplug_files())
    state = tmp_path / "state"
    (tmp_path / "served").mkdir(exist_ok=True)
    with catalog_app(tmp_path, tmp_path / "served", trust_root=trust, roots_factory=live_roots) as app:
        attach_runtime(app.client.app, state)
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL).json()
        sheet = sheet["detail"] if isinstance(sheet.get("detail"), dict) else sheet
        consent = {"digest": package.digest, "body_sha": sheet["body_sha"], "scripts": True, "cplug_accepted": True,
                   "cplug_facts_sha": sheet["cplug_facts_sha"]}
        assert app.client.raw_post("/catalog/install", json={**GLOBAL, "consent": consent}).status_code == 200
        (row,) = ledger_rows(app)
        assert identity.lookup(state, NAME) is not None
        assert app.client.delete(f"/catalog/installed/{row.install_id}").status_code == 200
        assert identity.lookup(state, NAME) is None
        assert NAME not in [r.name for r in identity.installs(state)]


def test_a_mismatched_name_is_refused_with_its_own_code(tmp_path):
    d = tmp_path / "pkg"
    for rel, body in cplug_files("other").items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(body)
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.evaluate(ITEM_ID, d)
    assert caught.value.code == install_gates.NAME_MISMATCH


def test_an_exec_member_and_a_shared_object_are_refused(tmp_path):
    def lay(extra, name) -> Path:
        folder = tmp_path / name
        for rel, body in cplug_files(extra=extra).items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(body)
        return folder

    ok = lay({}, "ok")
    assert install_gates.evaluate(ITEM_ID, ok).facts["id"] == NAME
    execd = lay({}, "execd")
    os.chmod(execd / "main.py", 0o755)
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.evaluate(ITEM_ID, execd)
    assert caught.value.code == install_gates.NOT_SAFE
    native = lay({"lib/native.so": b"\x7fELF"}, "native")
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.evaluate(ITEM_ID, native)
    assert caught.value.code == install_gates.NOT_SAFE
    linked = lay({}, "linked")
    (linked / "evil.py").symlink_to("/etc/passwd")
    with pytest.raises(install_gates.CplugGateRefusal) as caught:
        install_gates.evaluate(ITEM_ID, linked)
    assert caught.value.code == install_gates.NOT_SAFE
    assert stat.S_IMODE(os.lstat(ok / "main.py").st_mode) & 0o111 == 0


def test_a_plugin_update_asking_for_consent_carries_its_declared_facts(tmp_path):
    keys = keypairs(tmp_path / "keys")
    trust, package = publish(tmp_path, cplug_files(), keys=keys)
    state = tmp_path / "state"
    served = tmp_path / "served"
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=live_roots) as app:
        attach_runtime(app.client.app, state)
        sheet = app.client.post("/catalog/install/preview", json=GLOBAL).json()
        sheet = sheet["detail"] if isinstance(sheet.get("detail"), dict) else sheet
        consent = {"digest": package.digest, "body_sha": sheet["body_sha"], "scripts": True, "cplug_accepted": True,
                   "cplug_facts_sha": sheet["cplug_facts_sha"]}
        assert app.client.raw_post("/catalog/install", json={**GLOBAL, "consent": consent}).status_code == 200
        (row,) = ledger_rows(app)

        second_commit = "f" * 40
        index_kp, publisher_kp, _stranger = keys
        files = cplug_files()
        for member in ("cplug.json", "carnivore.json"):
            files[member] = json.dumps({**json.loads(files[member]), "version": "1.0.1"}).encode()
        second = build_skill(tmp_path, publisher=PUBLISHER, name=NAME, files=files, commit=second_commit, label="v2",
                             folder=kinds.archive_folder(kinds.KIND_CPLUG))
        serve_archive(served, second.tar_bytes, commit=second_commit)
        item = skill_item(NAME, PUBLISHER, second.digest, kind=kinds.KIND_CPLUG, repo=FIXTURE_REPO, commit=second_commit, version="1.0.1",
                          path=f"{kinds.archive_folder(kinds.KIND_CPLUG)}/{PUBLISHER}/{NAME}")
        publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=[item], serial=2)
        app.clock.advance(301)
        refreshed = app.client.post("/catalog/index/refresh")
        assert refreshed.status_code == 200, refreshed.text

        refused = app.client.raw_post(f"/catalog/installed/{row.install_id}/update", json={"expected_revision": row.revision})
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "consent_required" and detail["body_sha"]
        assert [p["name"] for p in detail["cplug_facts"]["permissions"]] == ["notify"]
        assert detail["cplug_facts_sha"]
