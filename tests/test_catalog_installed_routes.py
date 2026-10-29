
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cmr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cmr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api import catalog_installed_support
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    AUTO_UPDATE_GLOBAL_ONLY,
    CONSENT_REQUIRED,
    DIGEST_MISMATCH,
    STALE_REVISION,
)
from src.core.skills.journal_recovery import OUTCOME_FINISHED, recover_pending
from src.core.skills.records import SIDECAR_NAME, read_sidecar
from src.core.skills.targets import move_to_trash
from tests.helpers.catalog_app import catalog_app, ledger_rows
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
GLOBAL = {"item_id": ITEM_ID, "scope": "global"}

BODY_V1 = b"---\nname: sme\n---\n# sme\n\nthe sme skill\n"

BODY_V2 = b"---\nname: sme\n---\n# sme\n\nnow it also reads your mail\n"

SECOND_COMMIT = "c" * 40

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def publish_first(tmp_path, served, keys):
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files={"SKILL.md": BODY_V1}
    )
    serve_archive(served, package.tar_bytes)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(package, publisher=PUBLISHER, name=NAME)],
        serial=1,
    )
    return fixture_trust_root(index_kp, publisher_kp)


def publish_second(
    tmp_path,
    served,
    keys,
    *,
    body: bytes = BODY_V1,
    corrupt_archive: bool = False,
) -> None:
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files={"SKILL.md": body, "reference.md": b"# more\n"},
        commit=SECOND_COMMIT,
        label="v2",
    )
    if corrupt_archive:
        other = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name=NAME,
            files={"SKILL.md": body, "reference.md": b"# not the same\n"},
            commit=SECOND_COMMIT,
            label="v2-swapped",
        )
        serve_archive(served, other.tar_bytes, commit=SECOND_COMMIT)
    else:
        serve_archive(served, package.tar_bytes, commit=SECOND_COMMIT)

    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(
                package,
                publisher=PUBLISHER,
                name=NAME,
                version="2.0.0",
                commit=SECOND_COMMIT,
            )
        ],
        serial=2,
    )


def install(app, body: Optional[dict] = None):
    response = app.client.post("/catalog/install", json=body or GLOBAL)
    assert response.status_code == 200, response.text
    return response.json()


def refusal(response) -> dict:
    return response.json()["detail"]


def trash_names(app, harness: str, scope: str = "global", project=None) -> list:
    trash = app.roots.trash_dir(
        harness, scope, None if project is None else str(project)
    )
    if not trash.is_dir():
        return []
    return sorted(entry.name for entry in trash.iterdir() if entry.name != ".gitignore")


def journals(app) -> list:
    pending = app.roots.pending_dir()
    if not pending.is_dir():
        return []
    return sorted(entry.name for entry in pending.iterdir() if entry.is_file())


def root_entries(app, harness: str) -> list:
    root = app.roots.claude_skills() if harness == "claude" else app.roots.codex_skills()
    return sorted(entry.name for entry in root.iterdir())




def test_an_uninstall_moves_both_copies_to_the_trash_and_forgets_the_row(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        claude = app.roots.claude_skills() / NAME
        codex = app.roots.codex_skills() / NAME
        assert claude.is_dir() and codex.is_dir()

        response = app.client.delete(f"/catalog/installed/{row['install_id']}")
        after = ledger_rows(app)
        claude_trash = trash_names(app, "claude")
        codex_trash = trash_names(app, "codex")
        trashed = response.json()["trashed"]

    assert response.status_code == 200, response.text
    assert response.json()["install_id"] == row["install_id"]
    assert response.json()["missing"] == []
    assert claude.exists() is False
    assert codex.exists() is False
    assert len(claude_trash) == 1 and claude_trash[0].startswith(f"{NAME}-")
    assert len(codex_trash) == 1 and codex_trash[0].startswith(f"{NAME}-")
    for path in trashed:
        assert (Path(path) / "SKILL.md").read_bytes() == BODY_V1
    assert after == []


def test_uninstalling_something_that_is_not_there_is_a_404(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        first = app.client.delete(f"/catalog/installed/{row['install_id']}")
        second = app.client.delete(f"/catalog/installed/{row['install_id']}")
        unknown = app.client.delete("/catalog/installed/nosuchinstallid")

    assert first.status_code == 200, first.text
    assert second.status_code == 404, second.text
    assert unknown.status_code == 404, unknown.text


def test_a_copy_that_is_already_gone_is_reported_and_not_fatal(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        shutil.rmtree(app.roots.codex_skills() / NAME)

        response = app.client.delete(f"/catalog/installed/{row['install_id']}")
        after = ledger_rows(app)
        claude_trash = trash_names(app, "claude")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["trashed"]) == 1
    assert len(body["missing"]) == 1
    assert body["missing"][0].endswith(f"/.codex/skills/{NAME}")
    assert len(claude_trash) == 1
    assert after == [], "the row must be forgotten even so"




def test_the_patch_sets_auto_update_and_steps_the_revision(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        assert row["auto_update"] is False and row["revision"] == 1

        response = app.client.patch(
            f"/catalog/installed/{row['install_id']}",
            json={"auto_update": True, "expected_revision": 1},
        )
        stored = ledger_rows(app)[0]

    assert response.status_code == 200, response.text
    assert response.json()["auto_update"] is True
    assert response.json()["revision"] == 2
    assert stored.auto_update is True


def test_a_stale_revision_on_the_patch_carries_the_current_row(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        response = app.client.patch(
            f"/catalog/installed/{row['install_id']}",
            json={"auto_update": True, "expected_revision": 99},
        )
        stored = ledger_rows(app)[0]

    assert response.status_code == 409, response.text
    body = refusal(response)
    assert body["code"] == STALE_REVISION
    assert body["current"]["revision"] == 1
    assert body["current"]["install_id"] == row["install_id"]
    assert body["current"]["auto_update"] is False
    assert stored.auto_update is False, "a refused write must not have written"


def test_patching_an_unknown_install_is_a_404(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.patch(
            "/catalog/installed/nosuchinstallid",
            json={"auto_update": True, "expected_revision": 1},
        )

    assert response.status_code == 404, response.text


def test_auto_update_on_a_project_install_is_refused(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)
    project = tmp_path / "checkout"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)

    with catalog_app(
        tmp_path, served, trust_root=trust, projects=[project]
    ) as app:
        row = install(
            app,
            {
                "item_id": ITEM_ID,
                "scope": "project",
                "project_path": str(project),
            },
        )
        turning_on = app.client.patch(
            f"/catalog/installed/{row['install_id']}",
            json={"auto_update": True, "expected_revision": 1},
        )
        turning_off = app.client.patch(
            f"/catalog/installed/{row['install_id']}",
            json={"auto_update": False, "expected_revision": 1},
        )
        stored = ledger_rows(app)[0]

    assert turning_on.status_code == 409, turning_on.text
    assert refusal(turning_on)["code"] == AUTO_UPDATE_GLOBAL_ONLY
    assert turning_off.status_code == 200, turning_off.text
    assert stored.auto_update is False
    assert stored.revision == 2, "the refused write must not have stepped it"




def test_an_update_with_the_same_manifest_swaps_both_copies(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys)
        app.clock.advance(301.0)

        response = app.client.post(
            f"/catalog/installed/{row['install_id']}/update",
            json={"expected_revision": 1},
        )
        claude = app.roots.claude_skills() / NAME
        codex = app.roots.codex_skills() / NAME
        left_behind = app.staging_entries()
        entries = (root_entries(app, "claude"), root_entries(app, "codex"))
        claude_trash = trash_names(app, "claude")
        pending = journals(app)
        stored = ledger_rows(app)[0]

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == "2.0.0"
    assert body["revision"] == 2
    assert body["update_available"] is False

    for landed in (claude, codex):
        assert landed.is_dir() and landed.is_symlink() is False
        assert (landed / "SKILL.md").read_bytes() == BODY_V1
        assert (landed / "reference.md").read_bytes() == b"# more\n"
        record = read_sidecar(landed)
        assert record is not None and record.version == "2.0.0"
        assert (landed / SIDECAR_NAME).is_file()

    assert len(claude_trash) == 1, "the copy it replaced belongs in the trash"
    assert (
        Path(app.roots.trash_dir("claude", "global", None)) / claude_trash[0]
        / "reference.md"
    ).exists() is False, "the trashed copy is the OLD one"
    assert entries == ([NAME], [NAME]), "no incoming folder may be left behind"
    assert pending == [], "the journal is deleted when the swap completes"
    assert left_behind == []
    assert stored.version == "2.0.0"
    assert stored.digest == body["digest"]


def test_an_update_whose_manifest_changed_needs_fresh_consent(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys, body=BODY_V2)
        app.clock.advance(301.0)
        path = f"/catalog/installed/{row['install_id']}/update"

        refused = app.client.post(path, json={"expected_revision": 1})
        untouched = (app.roots.claude_skills() / NAME / "SKILL.md").read_bytes()
        body_sha = refusal(refused)["body_sha"]

        wrong = app.client.post(
            path,
            json={
                "expected_revision": 1,
                "consent": {"body_sha": "0" * 64},
            },
        )
        accepted = app.client.post(
            path,
            json={"expected_revision": 1, "consent": {"body_sha": body_sha}},
        )
        landed = (app.roots.claude_skills() / NAME / "SKILL.md").read_bytes()
        left_behind = app.staging_entries()

    assert refused.status_code == 409, refused.text
    sheet = refusal(refused)
    assert sheet["code"] == CONSENT_REQUIRED
    assert "reads your mail" in sheet["body"]
    assert len(body_sha) == 64
    assert untouched == BODY_V1, "a refusal must change nothing on disk"

    assert wrong.status_code == 409, wrong.text
    assert refusal(wrong)["code"] == CONSENT_REQUIRED

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["version"] == "2.0.0"
    assert landed == BODY_V2
    assert left_behind == []


def test_an_update_with_nothing_newer_is_already_installed(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        response = app.client.post(
            f"/catalog/installed/{row['install_id']}/update",
            json={"expected_revision": 1},
        )
        left_behind = app.staging_entries()

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == ALREADY_INSTALLED
    assert "up to date" in refusal(response)["detail"]
    assert left_behind == []


def test_a_stale_revision_on_the_update_refuses_before_a_byte_is_fetched(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys)
        app.clock.advance(301.0)
        before = [p for p in app.server.seen() if SECOND_COMMIT in p]

        response = app.client.post(
            f"/catalog/installed/{row['install_id']}/update",
            json={"expected_revision": 99},
        )
        after = [p for p in app.server.seen() if SECOND_COMMIT in p]
        stored = ledger_rows(app)[0]

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == STALE_REVISION
    assert refusal(response)["current"]["version"] == "1.0.0"
    assert after == before, "the new tarball must never have been requested"
    assert stored.version == "1.0.0"


def test_a_digest_mismatch_leaves_the_old_copy_and_no_journal(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys, corrupt_archive=True)
        app.clock.advance(301.0)

        response = app.client.post(
            f"/catalog/installed/{row['install_id']}/update",
            json={"expected_revision": 1},
        )
        landed = app.roots.claude_skills() / NAME
        entries = (root_entries(app, "claude"), root_entries(app, "codex"))
        pending = journals(app)
        left_behind = app.staging_entries()
        stored = ledger_rows(app)[0]

    assert response.status_code == 409, response.text
    assert refusal(response)["code"] == DIGEST_MISMATCH
    assert (landed / "SKILL.md").read_bytes() == BODY_V1
    assert (landed / "reference.md").exists() is False
    assert entries == ([NAME], [NAME])
    assert pending == [], "a refusal before the swap writes no journal"
    assert left_behind == []
    assert stored.version == "1.0.0" and stored.revision == 1


def test_a_crash_between_the_two_swaps_leaves_a_journal_recovery_finishes(
    tmp_path, served, keys, monkeypatch
):
    trust = publish_first(tmp_path, served, keys)
    calls: list[Any] = []
    real_swap = catalog_installed_support.apply_swap

    def crash_on_the_second(journal, *, roots):
        calls.append(journal)
        if len(calls) == 1:
            return real_swap(journal, roots=roots)
        move_to_trash(
            Path(journal.target), Path(journal.trash), journal.stamp
        )
        raise OSError("the power went out between the two renames")

    monkeypatch.setattr(
        catalog_installed_support, "apply_swap", crash_on_the_second
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        row = install(app)
        publish_second(tmp_path, served, keys)
        app.clock.advance(301.0)

        response = app.client.post(
            f"/catalog/installed/{row['install_id']}/update",
            json={"expected_revision": 1},
        )
        claude = app.roots.claude_skills() / NAME
        codex = app.roots.codex_skills() / NAME
        mid_crash = (
            claude.is_dir(),
            codex.exists(),
            journals(app),
            app.staging_entries(),
            ledger_rows(app)[0].version,
        )

        counts = recover_pending(app.roots.pending_dir(), app.roots)
        after = (
            (codex / "SKILL.md").read_bytes(),
            (codex / "reference.md").exists(),
            journals(app),
            root_entries(app, "codex"),
        )

    assert response.status_code == 500, response.text
    assert "journal" in response.json()["detail"]

    landed_first, second_gone, pending, staging, version = mid_crash
    assert landed_first is True, "the first target did swap"
    assert second_gone is False, "the second is mid-swap and nowhere"
    assert len(pending) == 1, "the interrupted target left its journal"
    assert staging == [], "the staged copy is still discarded on a failure"
    assert version == "1.0.0", "the row is not moved until every copy is"

    body, has_reference, cleared, entries = after
    assert counts[OUTCOME_FINISHED] == 1, counts
    assert body == BODY_V1
    assert has_reference is True, "recovery finished with the NEW copy"
    assert cleared == [], "a recovered journal is deleted"
    assert entries == [NAME], "and its staging folder goes with it"
