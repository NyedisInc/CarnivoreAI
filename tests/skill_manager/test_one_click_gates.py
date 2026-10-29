
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import Request

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_1c_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_1c_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.verify_types import KEY_UNTRUSTED
from src.core.live_install_roots import LiveInstallRoots
from src.core.skills.install_types import NO_HARNESS_PRESENT, SHEET_REQUIRED
from tests.helpers.catalog_app import catalog_app, ledger_rows
from tests.helpers.catalog_fixture import sign_item_versions
from tests.helpers.catalog_surface import (
    build_skill,
    fixture_trust_root,
    item_for,
    keypairs,
    publish_index,
    serve_archive,
)
from tests.helpers.minisign_keys import SKIP_REASON, minisign_binary

PUBLISHER = "alex"
NAME = "sme"
ITEM_ID = f"{PUBLISHER}/{NAME}"
GLOBAL_ONE_CLICK = {"item_id": ITEM_ID, "scope": "global", "one_click": True}
CLEAN = {
    "status": "reviewed",
    "verdict": "clean",
    "summary": "does what it says",
    "warnings": [],
}

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    (fake / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return fake


def _live(settings) -> LiveInstallRoots:
    return LiveInstallRoots(settings_reader=settings)


def _publish(tmp_path, served, keys, *, review=CLEAN, scripts=0, files=None,
             exec_paths=(), extra_items=()):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files=files, exec_paths=exec_paths
    )
    serve_archive(served, package.tar_bytes)
    item = item_for(package, publisher=PUBLISHER, name=NAME, scripts=scripts)
    if review is not None:
        item["versions"][0]["review"] = review
    publish_index(
        tmp_path, served, index_keypair=index_kp, publisher_keypair=publisher_kp,
        items=[item, *extra_items], serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp)


def _refusal(response) -> dict:
    return response.json()["detail"]


def _assert_sheet_required(app, response, reason: str, home: Path) -> None:
    assert response.status_code == 409, response.text
    body = _refusal(response)
    assert body["code"] == SHEET_REQUIRED, body
    assert body["reason"] == reason, body
    assert ledger_rows(app) == []
    assert not (home / ".claude" / "skills" / NAME).exists()
    assert app.staging_entries() == []


def test_a_clean_item_installs_in_one_click_and_the_ledger_says_so(
    tmp_path, served, keys, home
):
    trust = _publish(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        rows = ledger_rows(app)
    assert response.status_code == 200, response.text
    assert response.json()["consent_via"] == "one_click"
    assert [r.consent_via for r in rows] == ["one_click"]
    landed = home / ".claude" / "skills" / NAME
    assert (landed / "SKILL.md").is_file() and not landed.is_symlink()


def test_the_sheet_path_records_sheet_only_with_proof(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    body = {"item_id": ITEM_ID, "scope": "global"}
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        bare = app.client.raw_post("/catalog/install", json=body)
        _assert_sheet_required(app, bare, "no_sheet_proof", home)
        preview = app.client.post("/catalog/install/preview", json=body)
        assert preview.status_code == 200, preview.text
        token = preview.json()["plan_token"]
        response = app.client.raw_post("/catalog/install", json=dict(body, plan_token=token))
        rows = ledger_rows(app)
    assert response.status_code == 200, response.text
    assert [r.consent_via for r in rows] == ["sheet"]


def test_a_blueprint_install_needs_no_sheet_proof_and_records_blueprint(
    tmp_path, served, keys, home
):
    from src.api.catalog_install_routes import run_install
    from src.models.catalog_api import InstallRequest

    trust = _publish(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:

        async def _launch(request: Request):
            body = InstallRequest(item_id=ITEM_ID, scope="global")
            return await run_install(request, body, blueprint=True)

        app.client.app.add_api_route("/_bp_launch", _launch, methods=["POST"])
        response = app.client.raw_post("/_bp_launch")
        rows = ledger_rows(app)
    assert response.status_code == 200, response.text
    assert [r.consent_via for r in rows] == ["blueprint"]


def test_a_non_exec_interpreter_file_needs_the_sheet(tmp_path, served, keys, home):
    files = {
        "SKILL.md": b"---\nname: sme\n---\n# sme\n\nrun tools/run.py\n",
        "tools/run.py": b"print('hi')\n",
    }
    trust = _publish(tmp_path, served, keys, scripts=0, files=files)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        _assert_sheet_required(app, response, "scripts", home)


def test_declared_scripts_need_the_sheet_and_fetch_nothing(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys, scripts=1)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        fetched = [p for p in app.server.seen() if "tar.gz" in p]
        _assert_sheet_required(app, response, "scripts", home)
    assert fetched == []


def test_a_scripts_consent_never_rides_in_on_one_click(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys, scripts=1)
    body = dict(GLOBAL_ONE_CLICK, consent={"scripts": True, "digest": "0" * 64, "body_sha": "0" * 64})
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        _assert_sheet_required(app, response, "scripts", home)


def test_scripts_the_index_did_not_declare_need_the_sheet(tmp_path, served, keys, home):
    files = {
        "SKILL.md": b"---\nname: sme\n---\n# sme\n\nthe sme skill\n",
        "scripts/run.sh": b"#!/bin/sh\necho hi\n",
    }
    trust = _publish(tmp_path, served, keys, scripts=0, files=files,
                     exec_paths=("scripts/run.sh",))
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        _assert_sheet_required(app, response, "scripts", home)


@pytest.mark.parametrize(
    "review",
    [
        None,
        {"status": "unavailable"},
        {"status": "reviewed", "verdict": "flagged", "summary": "x",
         "warnings": [{"kind": "network", "detail": "calls out", "file": "SKILL.md"}]},
        {"status": "reviewed", "verdict": "clean", "summary": "x",
         "warnings": [{"kind": "network", "detail": "calls out", "file": "SKILL.md"}]},
        {"status": "reviewed", "verdict": "blocked", "summary": "x", "warnings": [],
         "override": {"reason": "maintainer says fine"}},
    ],
    ids=["no-review", "unavailable", "flagged", "clean-with-warning", "blocked-overridden"],
)
def test_a_review_that_is_not_clean_needs_the_sheet(tmp_path, served, keys, home, review):
    trust = _publish(tmp_path, served, keys, review=review)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        _assert_sheet_required(app, response, "review_not_clean", home)


def test_a_name_collision_needs_the_sheet_and_touches_nothing(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    theirs = home / ".claude" / "skills" / NAME
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("mine\n")
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        assert response.status_code == 409, response.text
        assert _refusal(response)["code"] == SHEET_REQUIRED
        assert _refusal(response)["reason"] == "name_collision"
        assert ledger_rows(app) == []
        assert app.staging_entries() == []
    assert (theirs / "SKILL.md").read_text() == "mine\n"


def test_a_replace_choice_is_never_one_click(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    theirs = home / ".claude" / "skills" / NAME
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("mine\n")
    body = dict(GLOBAL_ONE_CLICK, choice="replace")
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 409, response.text
        assert _refusal(response)["reason"] == "choice_given"
        assert ledger_rows(app) == []
    assert (theirs / "SKILL.md").read_text() == "mine\n"


def test_an_untrusted_signer_is_refused_outright_in_one_click(tmp_path, served, keys, home):
    _index_kp, _publisher_kp, stranger_kp = keys
    theirs = build_skill(tmp_path, publisher="stranger", name="other", label="theirs")
    stranger_item = sign_item_versions(
        tmp_path, item_for(theirs, publisher="stranger", name="other"), stranger_kp
    )
    trust = _publish(tmp_path, served, keys, extra_items=(stranger_item,))
    body = {"item_id": "stranger/other", "scope": "global", "one_click": True}
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 409, response.text
        assert _refusal(response)["code"] == KEY_UNTRUSTED
        assert ledger_rows(app) == []


def test_a_claude_only_machine_installs_without_codex_folders(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=GLOBAL_ONE_CLICK)
        rows = ledger_rows(app)
        with app.services.catalog.ledger() as ledger:
            targets = ledger.targets(rows[0].install_id)
    assert response.status_code == 200, response.text
    assert [t.harness for t in targets] == ["claude"]
    assert not (home / ".codex").exists()
    assert not (home / ".agents").exists()


def test_a_missing_leaf_folder_is_created_only_when_asked(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    plain = dict(GLOBAL_ONE_CLICK)
    (home / ".claude" / "skills").rmdir()
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        refused = app.client.post("/catalog/install", json=plain)
        assert refused.status_code == 409 and _refusal(refused)["code"] == "root_absent"
        assert not (home / ".claude" / "skills").exists()
        made = app.client.post("/catalog/install", json=dict(plain, create_roots=True))
    assert made.status_code == 200, made.text
    assert (home / ".claude" / "skills" / NAME / "SKILL.md").is_file()


def test_no_agent_present_refuses_and_creates_nothing(tmp_path, served, keys, monkeypatch):
    fake = tmp_path / "emptyhome"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    trust = _publish(tmp_path, served, keys)
    body = dict(GLOBAL_ONE_CLICK, create_roots=True)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 409, response.text
        assert _refusal(response)["code"] == NO_HARNESS_PRESENT
    assert list(fake.iterdir()) == []


def test_a_new_global_codex_install_lands_in_agents_skills(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    (home / ".codex").mkdir()
    body = dict(GLOBAL_ONE_CLICK, create_roots=True)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        rows = ledger_rows(app)
        with app.services.catalog.ledger() as ledger:
            targets = {t.harness: t.path for t in ledger.targets(rows[0].install_id)}
    assert response.status_code == 200, response.text
    assert targets["codex"] == str(home / ".agents" / "skills" / NAME)
    assert (home / ".agents" / "skills" / NAME / "SKILL.md").is_file()
    assert not (home / ".codex" / "skills").exists()


def test_harnesses_can_only_narrow_never_add(tmp_path, served, keys, home):
    trust = _publish(tmp_path, served, keys)
    body = dict(GLOBAL_ONE_CLICK, harnesses=["codex"], create_roots=True)
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        response = app.client.post("/catalog/install", json=body)
        assert response.status_code == 409, response.text
        assert _refusal(response)["code"] == NO_HARNESS_PRESENT
    assert not (home / ".agents").exists()


def test_an_old_codex_row_still_uninstalls_from_its_recorded_path(
    tmp_path, served, keys, home
):
    trust = _publish(tmp_path, served, keys)
    (home / ".codex").mkdir()
    old_root = home / ".codex" / "skills"
    with catalog_app(tmp_path, served, trust_root=trust, roots_factory=_live) as app:
        made = app.client.post("/catalog/install", json=dict(GLOBAL_ONE_CLICK, create_roots=True))
        assert made.status_code == 200, made.text
        row = ledger_rows(app)[0]
        new_copy = home / ".agents" / "skills" / NAME
        old_copy = old_root / NAME
        old_root.mkdir(parents=True)
        new_copy.rename(old_copy)
        shutil.rmtree(home / ".agents")
        with app.services.catalog.ledger() as ledger:
            conn = ledger._conn
            conn.execute(
                "UPDATE installed_item_targets SET path = ? WHERE install_id = ? AND harness = 'codex'",
                (str(old_copy), row.install_id),
            )
            conn.commit()
        gone = app.client.delete(f"/catalog/installed/{row.install_id}")
        assert gone.status_code == 200, gone.text
        assert ledger_rows(app) == []
    assert not old_copy.exists()
    assert not (home / ".agents").exists()
    trashed = [
        p for p in (home / ".codex" / ".carnivore-trash").iterdir()
        if p.name != ".gitignore"
    ]
    assert len(trashed) == 1 and trashed[0].name.startswith(NAME)
