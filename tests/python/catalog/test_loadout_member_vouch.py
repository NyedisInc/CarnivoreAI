
from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_fixture import revocation_entry, sign_item_versions
from tests.helpers.catalog_surface import (
    build_loadout,
    build_skill,
    fixture_trust_root,
    item_for,
    keypairs,
    loadout_item_for,
    member_ref,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
LOADOUT_ID = f"{PUBLISHER}/pinned"
GLOBAL = {"item_id": LOADOUT_ID, "scope": "global"}
COMMITS = {"good": "1" * 40, "revoked": "2" * 40, "tampered": "3" * 40, "loadout": "4" * 40}

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


def _two_versions(item: dict, pinned: str) -> dict:
    older = copy.deepcopy(item["versions"][0])
    older["v"] = pinned
    newer = copy.deepcopy(item["versions"][0])
    newer["v"] = "2.0.0"
    item["versions"] = [newer, older]
    item["latest"] = "2.0.0"
    return item


def _publish(tmp_path: Path, served: Path):
    index_kp, publisher_kp, _stranger = keypairs(tmp_path / "keys")
    packages, items = {}, []
    pins = {"good": "1.0.0", "revoked": "0.9.0", "tampered": "1.1.0"}
    for name, pinned in pins.items():
        pkg = build_skill(tmp_path, publisher=PUBLISHER, name=name, commit=COMMITS[name], label=name)
        serve_archive(served, pkg.tar_bytes, commit=COMMITS[name])
        item = _two_versions(item_for(pkg, publisher=PUBLISHER, name=name, commit=COMMITS[name]), pinned)
        sign_item_versions(tmp_path, item, publisher_kp)
        packages[name] = (pkg, pinned)
        items.append(item)
    tampered = next(i for i in items if i["name"] == "tampered")
    by_v = {v["v"]: v for v in tampered["versions"]}
    by_v["1.1.0"]["sig"] = copy.deepcopy(by_v["2.0.0"]["sig"])
    loadout = build_loadout(
        tmp_path, publisher=PUBLISHER, name="pinned", commit=COMMITS["loadout"], label="l",
        members=[member_ref(pkg, publisher=PUBLISHER, name=name, version=pinned) for name, (pkg, pinned) in packages.items()],
    )
    serve_archive(served, loadout.tar_bytes, commit=COMMITS["loadout"])
    items.append(loadout_item_for(loadout, publisher=PUBLISHER, name="pinned", commit=COMMITS["loadout"]))
    revoked = revocation_entry(tmp_path, kind="version", subject=f"{PUBLISHER}/revoked@0.9.0", since="2026-09-02T00:00:00+00:00", keypair=publisher_kp)
    publish_index(tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp, items=items,
                  revocations={"keys": [], "versions": [revoked]})
    return fixture_trust_root(index_kp, publisher_kp)


def test_a_revoked_or_tampered_pinned_version_installs_nothing_and_a_valid_one_still_does(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    trust = _publish(tmp_path, served)
    with catalog_app(tmp_path, served, trust_root=trust) as app:
        answer = app.client.post("/catalog/install", json=GLOBAL)
        assert answer.status_code == 200, answer.text
        members = {m["item_id"]: m for m in answer.json()["members"]}

        assert members[f"{PUBLISHER}/revoked"]["state"] == "refused"
        assert members[f"{PUBLISHER}/revoked"]["code"] == "version_revoked"
        assert members[f"{PUBLISHER}/tampered"]["state"] == "refused"
        assert members[f"{PUBLISHER}/tampered"]["code"] == "signature_invalid"
        assert members[f"{PUBLISHER}/good"]["state"] == "installed"
        assert answer.json()["complete"] is False

        installed = {row.item_id for row in ledger_rows(app)}
        assert installed == {LOADOUT_ID, f"{PUBLISHER}/good"}
        skills = app.roots.home / ".claude" / "skills"
        assert (skills / "good").is_dir()
        assert not (skills / "revoked").exists()
        assert not (skills / "tampered").exists()
