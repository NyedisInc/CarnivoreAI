
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.project_store import (
    import_from_config,
    list_projects,
    normalize_root,
)
from src.core.project_tombstones import record_tombstone
from src.core.projects_config_migration import migrate_projects_out_of_config
from src.core.project_writes import delete_project
from types import SimpleNamespace


def _cfg(name, path):
    return SimpleNamespace(
        name=name, path=path, description=None, agent_type="claude"
    )


def _write_config(path: Path, entries) -> None:
    path.write_text(
        json.dumps(
            {
                "config_version": 4,
                "projects": [
                    {"name": e.name, "path": e.path, "description": None}
                    for e in entries
                ],
            },
            indent=2,
        )
    )


@pytest.fixture()
def install(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    return SimpleNamespace(
        state_dir=tmp_path, config_file=tmp_path / "config.json"
    )


def test_a_project_created_while_downgraded_survives_the_re_upgrade(install):
    with closing(connect(db_path_for(install.state_dir))) as conn:
        with transaction(conn):
            import_from_config(conn, [_cfg("alpha", "/tmp/alpha")])

    _write_config(
        install.config_file,
        [_cfg("alpha", "/tmp/alpha"), _cfg("new", "/tmp/new")],
    )

    result = migrate_projects_out_of_config(
        install.state_dir, install.config_file
    )

    assert result.ok is True
    assert [e["root"] for e in result.imported] == [normalize_root("/tmp/new")]
    assert result.already_present == 1

    with closing(connect(db_path_for(install.state_dir))) as conn:
        roots = {row["root"] for row in list_projects(conn)}
    assert normalize_root("/tmp/new") in roots
    assert "projects" not in json.loads(install.config_file.read_text())


def test_a_deletion_made_in_the_NEW_version_is_never_undone(install):
    with closing(connect(db_path_for(install.state_dir))) as conn:
        with transaction(conn):
            import_from_config(
                conn, [_cfg("alpha", "/tmp/alpha"), _cfg("doomed", "/tmp/doomed")]
            )
        doomed = next(
            row
            for row in list_projects(conn)
            if row["root"] == normalize_root("/tmp/doomed")
        )
        delete_project(conn, doomed["id"])
        conn.commit()

    _write_config(
        install.config_file,
        [_cfg("alpha", "/tmp/alpha"), _cfg("doomed", "/tmp/doomed")],
    )

    result = migrate_projects_out_of_config(
        install.state_dir, install.config_file
    )

    assert result.imported == []
    assert [e["root"] for e in result.skipped_deleted] == [
        normalize_root("/tmp/doomed")
    ]

    with closing(connect(db_path_for(install.state_dir))) as conn:
        roots = {row["root"] for row in list_projects(conn)}
    assert normalize_root("/tmp/doomed") not in roots, (
        "the migration resurrected a project the user deliberately deleted"
    )


def test_the_migration_is_idempotent_across_repeated_starts(install):
    _write_config(install.config_file, [_cfg("alpha", "/tmp/alpha")])

    first = migrate_projects_out_of_config(install.state_dir, install.config_file)
    second = migrate_projects_out_of_config(install.state_dir, install.config_file)

    assert first.ok is True
    assert len(first.imported) == 1
    assert second.ok is True
    assert second.reason == "nothing_to_do"
    assert second.imported == []

    with closing(connect(db_path_for(install.state_dir))) as conn:
        assert len(list_projects(conn)) == 1, "a second pass double-imported"


def test_an_unrelated_config_key_survives_the_migration(install):
    install.config_file.write_text(
        json.dumps(
            {
                "config_version": 4,
                "template_path": "claude-template",
                "projects": [{"name": "alpha", "path": "/tmp/alpha"}],
                "agents": {"wrappers": {"claude": "/usr/bin/claude"}},
            },
            indent=2,
        )
    )

    assert migrate_projects_out_of_config(
        install.state_dir, install.config_file
    ).ok

    doc = json.loads(install.config_file.read_text())
    assert doc["template_path"] == "claude-template"
    assert doc["agents"] == {"wrappers": {"claude": "/usr/bin/claude"}}
    assert doc["config_version"] == 4
    assert "projects" not in doc


def test_a_tombstoned_root_does_not_block_the_key_from_being_dropped(install):
    with closing(connect(db_path_for(install.state_dir))) as conn:
        with transaction(conn):
            record_tombstone(conn, normalize_root("/tmp/gone"), "gone")

    _write_config(install.config_file, [_cfg("gone", "/tmp/gone")])

    result = migrate_projects_out_of_config(
        install.state_dir, install.config_file
    )

    assert result.ok is True
    assert result.imported == []
    assert len(result.skipped_deleted) == 1
    assert "projects" not in json.loads(install.config_file.read_text())
