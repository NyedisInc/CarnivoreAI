
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_aup_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_aup_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills import auto_update as auto_update_module
from src.core.skills.auto_update import (
    NOT_IN_INDEX,
    OUTCOME_FAILED,
    after_refresh_hook,
    run_auto_update_pass,
)
from src.core.skills.installer import iso_from
from src.core.skills.updates import (
    BODY_CHANGED,
    SCRIPTS_PRESENT,
    VERSION_UNCHANGED,
)
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
from tests.test_catalog_installed_routes import (
    BODY_V1,
    BODY_V2,
    GLOBAL,
    ITEM_ID,
    NAME,
    PUBLISHER,
    SECOND_COMMIT,
    install,
    publish_first,
    publish_second,
    trash_names,
)

MAIN_SOURCE = ROOT / "src" / "core" / "boot" / "background.py"

OTHER_REPO = "carnivore-ai/other"

pytestmark = pytest.mark.skipif(minisign_binary() is None, reason=SKIP_REASON)


@pytest.fixture
def served(tmp_path) -> Path:
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def keys(tmp_path):
    return keypairs(tmp_path / "keys")


def arm(app, row: dict) -> dict:
    response = app.client.patch(
        f"/catalog/installed/{row['install_id']}",
        json={"auto_update": True, "expected_revision": row["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def refresh(app) -> None:
    app.clock.advance(301)
    response = app.client.post("/catalog/index/refresh")
    assert response.status_code == 200, response.text
    assert response.json()["refreshed"] is True


def run_pass(app):
    return app.client.portal.call(run_auto_update_pass, app.services)


def version_now(app) -> str:
    rows = ledger_rows(app)
    assert len(rows) == 1
    return rows[0].version


def reasons(report) -> list:
    return [row.reason for row in report.rows]




def test_an_eligible_row_is_updated_and_the_old_copy_goes_to_the_trash(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        publish_second(tmp_path, served, keys, body=BODY_V1)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "2.0.0"
        landed = app.roots.claude_skills() / NAME
        assert (landed / "reference.md").is_file()
        assert trash_names(app, "claude") != []

    assert report.considered == 1
    assert [row.outcome for row in report.rows] == ["updated"]


def test_pressing_refresh_is_what_applies_it(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        cache = app.services.catalog.index_cache
        cache.after_refresh = after_refresh_hook(app.services)
        arm(app, install(app))
        publish_second(tmp_path, served, keys, body=BODY_V1)

        refresh(app)
        assert cache.after_refresh_task is not None
        app.client.portal.call(lambda: asyncio.wait_for(cache.after_refresh_task, 60))

        assert version_now(app) == "2.0.0"




def test_a_row_with_auto_update_off_is_never_considered(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        install(app)
        publish_second(tmp_path, served, keys, body=BODY_V1)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"

    assert report.considered == 0
    assert report.rows == ()


def test_a_project_copy_is_never_considered_even_when_the_column_says_so(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)
    project = tmp_path / "project"
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
        with app.services.catalog.ledger() as ledger:
            ledger.update(
                row["install_id"],
                expected_revision=row["revision"],
                now=iso_from(app.clock),
                auto_update=True,
            )

        publish_second(tmp_path, served, keys, body=BODY_V1)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"

    assert report.considered == 0
    assert report.rows == ()


def test_a_changed_manifest_is_skipped_and_keeps_its_badge(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        publish_second(tmp_path, served, keys, body=BODY_V2)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"
        assert (app.roots.claude_skills() / NAME / "SKILL.md").read_bytes() == (
            BODY_V1
        )

    assert reasons(report) == [BODY_CHANGED]


def test_a_release_that_grew_a_script_is_skipped(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        _publish_with_scripts(tmp_path, served, keys)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"
        assert not (app.roots.claude_skills() / NAME / "scripts").exists()

    assert reasons(report) == [SCRIPTS_PRESENT]


def test_a_digest_that_moved_under_one_version_string_is_refused(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        _republish_same_version(tmp_path, served, keys)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"

    assert reasons(report) == [VERSION_UNCHANGED]


def test_an_item_the_index_no_longer_carries_is_skipped(
    tmp_path, served, keys
):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        _publish_empty_index(tmp_path, served, keys)
        refresh(app)

        report = run_pass(app)

        assert version_now(app) == "1.0.0"
        assert (app.roots.claude_skills() / NAME).is_dir()

    assert reasons(report) == [NOT_IN_INDEX]




def test_two_passes_never_run_at_once(tmp_path, served, keys):
    trust = publish_first(tmp_path, served, keys)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        publish_second(tmp_path, served, keys, body=BODY_V1)
        refresh(app)

        async def both():
            return await asyncio.gather(
                run_auto_update_pass(app.services),
                run_auto_update_pass(app.services),
            )

        first, second = app.client.portal.call(both)

        assert version_now(app) == "2.0.0"

    busy = [report.busy for report in (first, second)]
    assert sorted(busy) == [False, True]


def test_one_row_that_cannot_be_fetched_does_not_stop_the_others(
    tmp_path, served, keys
):
    index_kp, publisher_kp, _stranger = keys
    first_v1 = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files={"SKILL.md": BODY_V1}
    )
    other_v1 = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name="other",
        files={"SKILL.md": BODY_V1},
        label="other-v1",
    )
    serve_archive(served, first_v1.tar_bytes)
    serve_archive(served, other_v1.tar_bytes, repo=OTHER_REPO)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(first_v1, publisher=PUBLISHER, name=NAME),
            item_for(
                other_v1, publisher=PUBLISHER, name="other", repo=OTHER_REPO
            ),
        ],
        serial=1,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        arm(
            app,
            install(app, {"item_id": f"{PUBLISHER}/other", "scope": "global"}),
        )

        first_v2 = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name=NAME,
            files={"SKILL.md": BODY_V1, "reference.md": b"# more\n"},
            commit=SECOND_COMMIT,
            label="first-v2",
        )
        other_v2 = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name="other",
            files={"SKILL.md": BODY_V1, "reference.md": b"# more\n"},
            commit=SECOND_COMMIT,
            label="other-v2",
        )
        serve_archive(
            served, other_v2.tar_bytes, repo=OTHER_REPO, commit=SECOND_COMMIT
        )
        publish_index(
            tmp_path,
            served,
            index_keypair=index_kp,
            publisher_keypair=publisher_kp,
            items=[
                item_for(
                    first_v2,
                    publisher=PUBLISHER,
                    name=NAME,
                    version="2.0.0",
                    commit=SECOND_COMMIT,
                ),
                item_for(
                    other_v2,
                    publisher=PUBLISHER,
                    name="other",
                    version="2.0.0",
                    commit=SECOND_COMMIT,
                    repo=OTHER_REPO,
                ),
            ],
            serial=2,
        )
        refresh(app)

        report = run_pass(app)

        by_item = {row.item_id: row for row in ledger_rows(app)}
        assert by_item[f"{PUBLISHER}/other"].version == "2.0.0"
        assert by_item[ITEM_ID].version == "1.0.0"
        assert app.staging_entries() == []

    assert report.considered == 2
    assert len(report.updated) == 1
    assert [row.item_id for row in report.failed] == [ITEM_ID]
    assert report.failed[0].outcome == OUTCOME_FAILED


def test_a_row_that_raises_where_nothing_catches_does_not_stop_the_others(
    tmp_path, served, keys, monkeypatch
):
    index_kp, publisher_kp, _stranger = keys
    first_v1 = build_skill(
        tmp_path, publisher=PUBLISHER, name=NAME, files={"SKILL.md": BODY_V1}
    )
    other_v1 = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name="other",
        files={"SKILL.md": BODY_V1},
        label="other-v1",
    )
    serve_archive(served, first_v1.tar_bytes)
    serve_archive(served, other_v1.tar_bytes, repo=OTHER_REPO)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            item_for(first_v1, publisher=PUBLISHER, name=NAME),
            item_for(
                other_v1, publisher=PUBLISHER, name="other", repo=OTHER_REPO
            ),
        ],
        serial=1,
    )
    trust = fixture_trust_root(index_kp, publisher_kp)

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, install(app))
        arm(
            app,
            install(app, {"item_id": f"{PUBLISHER}/other", "scope": "global"}),
        )

        first_v2 = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name=NAME,
            files={"SKILL.md": BODY_V1, "reference.md": b"# more\n"},
            commit=SECOND_COMMIT,
            label="first-v2",
        )
        other_v2 = build_skill(
            tmp_path,
            publisher=PUBLISHER,
            name="other",
            files={"SKILL.md": BODY_V1, "reference.md": b"# more\n"},
            commit=SECOND_COMMIT,
            label="other-v2",
        )
        serve_archive(served, first_v2.tar_bytes, commit=SECOND_COMMIT)
        serve_archive(
            served, other_v2.tar_bytes, repo=OTHER_REPO, commit=SECOND_COMMIT
        )
        publish_index(
            tmp_path,
            served,
            index_keypair=index_kp,
            publisher_keypair=publisher_kp,
            items=[
                item_for(
                    first_v2,
                    publisher=PUBLISHER,
                    name=NAME,
                    version="2.0.0",
                    commit=SECOND_COMMIT,
                ),
                item_for(
                    other_v2,
                    publisher=PUBLISHER,
                    name="other",
                    version="2.0.0",
                    commit=SECOND_COMMIT,
                    repo=OTHER_REPO,
                ),
            ],
            serial=2,
        )
        refresh(app)

        honest = auto_update_module.hash_file
        calls = {"n": 0}

        def raise_once(path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("staging vanished between the stage and the hash")
            return honest(path)

        monkeypatch.setattr(auto_update_module, "hash_file", raise_once)

        report = run_pass(app)

        versions = {row.item_id: row.version for row in ledger_rows(app)}
        assert app.staging_entries() == []

    assert calls["n"] == 2, "the second row was never reached"
    assert report.considered == 2
    assert len(report.failed) == 1
    assert len(report.updated) == 1
    assert report.failed[0].outcome == OUTCOME_FAILED
    assert report.failed[0].reason == "OSError"
    broke = report.failed[0].item_id
    survived = report.updated[0].item_id
    assert broke != survived
    assert versions[broke] == "1.0.0"
    assert versions[survived] == "2.0.0"


def test_the_boot_wiring_exists(tmp_path, served, keys):
    source = MAIN_SOURCE.read_text()

    assert "after_refresh_hook(services)" in source
    assert "run_auto_update_pass(services)" in source
    boot = source[source.index("async def _boot_auto_update"):]
    journal_wait = boot.index("skill_journal_task")
    pass_await = boot.index("await run_auto_update_pass")
    assert journal_wait < pass_await




def _publish_with_scripts(tmp_path, served, keys) -> None:
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files={"SKILL.md": BODY_V1, "scripts/run.sh": b"#!/bin/sh\n"},
        exec_paths=("scripts/run.sh",),
        commit=SECOND_COMMIT,
        label="v2-scripts",
    )
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
                scripts=1,
            )
        ],
        serial=2,
    )


def _republish_same_version(tmp_path, served, keys) -> None:
    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=PUBLISHER,
        name=NAME,
        files={"SKILL.md": BODY_V1, "reference.md": b"# recut\n"},
        commit=SECOND_COMMIT,
        label="recut",
    )
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
                version="1.0.0",
                commit=SECOND_COMMIT,
            )
        ],
        serial=2,
    )


def _publish_empty_index(tmp_path, served, keys) -> None:
    index_kp, publisher_kp, _stranger = keys
    other = build_skill(
        tmp_path, publisher=PUBLISHER, name="other", label="withdrawn"
    )
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[item_for(other, publisher=PUBLISHER, name="other")],
        serial=2,
    )



THEME_PUBLISHER = "nyedis"
THEME_NAME = "neon"
THEME_ITEM_ID = f"{THEME_PUBLISHER}/{THEME_NAME}"
THEME_COMMIT_V1 = "e" * 40
THEME_COMMIT_V2 = "f" * 40

DECOY_SKILL_MD = b"---\nname: neon\n---\n# neon\n\nnothing to see here\n"


def _theme_json(description: str) -> bytes:
    import json

    from tests.helpers.catalog_surface import theme_manifest

    manifest = json.loads(theme_manifest(THEME_NAME).decode())
    manifest["description"] = description
    return json.dumps(manifest, indent=2).encode()


def _publish_theme_version(
    tmp_path, served, keys, *, files, commit, version, serial
):
    from tests.helpers.catalog_surface import (
        ARCHIVE_FOLDER_THEME,
        build_skill,
        theme_item_for,
    )

    index_kp, publisher_kp, _stranger = keys
    package = build_skill(
        tmp_path,
        publisher=THEME_PUBLISHER,
        name=THEME_NAME,
        files=files,
        folder=ARCHIVE_FOLDER_THEME,
        commit=commit,
        label=f"theme-{version}",
    )
    serve_archive(served, package.tar_bytes, commit=commit)
    publish_index(
        tmp_path,
        served,
        index_keypair=index_kp,
        publisher_keypair=publisher_kp,
        items=[
            theme_item_for(
                package,
                publisher=THEME_PUBLISHER,
                name=THEME_NAME,
                commit=commit,
                version=version,
            )
        ],
        serial=serial,
    )
    return fixture_trust_root(index_kp, publisher_kp)


def _install_theme(app):
    response = app.client.post(
        "/catalog/install", json={"item_id": THEME_ITEM_ID, "scope": "global"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_theme_row_is_auto_updated_and_the_pass_drops_its_stale_run_grant(
    tmp_path, served, keys
):
    trust = _publish_theme_version(
        tmp_path,
        served,
        keys,
        files={"theme.json": _theme_json("v1")},
        commit=THEME_COMMIT_V1,
        version="1.0.0",
        serial=1,
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        arm(app, _install_theme(app))
        app.prefs.update(
            {
                "theme_script_consent": {
                    THEME_NAME: {"decision": "always", "digest": "a" * 64}
                }
            }
        )
        assert app.prefs.read()["values"]["theme_script_consent"][THEME_NAME]

        _publish_theme_version(
            tmp_path,
            served,
            keys,
            files={"theme.json": _theme_json("v1"), "extra.png": b"\x89PNG\r\n"},
            commit=THEME_COMMIT_V2,
            version="2.0.0",
            serial=2,
        )
        refresh(app)

        report = run_pass(app)

        assert [row.outcome for row in report.rows] == ["updated"], reasons(report)
        assert (app.roots.themes_dir() / THEME_NAME / "extra.png").is_file()
        held = app.prefs.read()["values"].get("theme_script_consent") or {}
        assert THEME_NAME not in held, (
            "the automatic pass must drop a grant naming bytes that are gone"
        )


def test_a_decoy_skill_md_in_a_theme_is_refused_at_install(
    tmp_path, served, keys
):
    trust = _publish_theme_version(
        tmp_path,
        served,
        keys,
        files={"theme.json": _theme_json("v1"), "SKILL.md": DECOY_SKILL_MD},
        commit=THEME_COMMIT_V1,
        version="1.0.0",
        serial=1,
    )

    with catalog_app(tmp_path, served, trust_root=trust) as app:
        response = app.client.post(
            "/catalog/install", json={"item_id": THEME_ITEM_ID, "scope": "global"}
        )
        assert response.status_code != 200, response.text
        assert "scripts_not_supported" in response.text
        assert not (app.roots.themes_dir() / THEME_NAME / "SKILL.md").exists()
