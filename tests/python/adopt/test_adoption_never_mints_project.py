
from __future__ import annotations

import ast
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import PROJECT_SOURCE_ADOPTION, SESSION_ATTRIBUTION_NONE
from src.core.session_project_binding import (
    BINDING_CREATED,
    BINDING_MATCHED,
    BINDING_NONE,
    resolve_project_binding,
)

SRC = Path(__file__).resolve().parents[3] / "src"
WRITES_PROJECTS = ("INTO projects", "create_project(")


def _project_writer_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if any(m in p.read_text(encoding="utf-8") for m in WRITES_PROJECTS)]


def test_nothing_in_src_can_write_the_adoption_source():
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "PROJECT_SOURCE_ADOPTION" and path.name != "db_models.py":
                offenders.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.alias) and node.name == "PROJECT_SOURCE_ADOPTION" and path.name != "db_models.py":
                offenders.append(f"{path}: imports it")
    for path in (p for p in _project_writer_files() if p.name != "db_models.py"):
        text = path.read_text(encoding="utf-8")
        if "'adoption'" in text or '"adoption"' in text:
            offenders.append(f"{path}: literal 'adoption' in a module that writes projects")
    assert offenders == []


@pytest.fixture
def conn(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    with closing(connect(db_path_for(state))) as c:
        yield c


def _add_project(conn, root: Path, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at) "
        "VALUES (?, ?, ?, 'user', 'unchecked', 't', 't')", (str(root), str(root), name))
    return int(cur.lastrowid)


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]


def test_a_sign_in_account_folder_never_becomes_a_project(conn, tmp_path, monkeypatch):
    accounts = tmp_path / "accounts"
    folder = accounts / "codex"
    folder.mkdir(parents=True)
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(accounts))
    binding = resolve_project_binding(conn, str(folder), allow_create=True)
    assert (binding.rule, binding.attribution, binding.project_id) == (BINDING_NONE, SESSION_ATTRIBUTION_NONE, None)
    assert binding.created_project is False
    assert _count(conn) == 0


def test_a_folder_gone_from_disk_never_becomes_a_project(conn, tmp_path):
    binding = resolve_project_binding(conn, str(tmp_path / "asd"), allow_create=True)
    assert binding.rule == BINDING_NONE and _count(conn) == 0


def test_a_real_folder_a_user_creates_in_is_minted_as_user_never_adoption(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(tmp_path / "accounts"))
    folder = tmp_path / "work" / "app"
    folder.mkdir(parents=True)
    binding = resolve_project_binding(conn, str(folder), allow_create=True)
    assert binding.rule == BINDING_CREATED
    source = conn.execute("SELECT source FROM projects WHERE id = ?", (binding.project_id,)).fetchone()[0]
    assert source == "user" and source != PROJECT_SOURCE_ADOPTION


def test_adoption_files_under_the_deepest_containing_project_and_mints_nothing(conn, tmp_path):
    outer, inner = tmp_path / "org", tmp_path / "org" / "team"
    deep = inner / "svc" / "src"
    deep.mkdir(parents=True)
    _add_project(conn, outer, "org")
    inner_id = _add_project(conn, inner, "team")
    before = _count(conn)
    binding = resolve_project_binding(conn, str(deep), allow_create=False)
    assert binding.rule == BINDING_MATCHED and binding.project_id == inner_id
    assert _count(conn) == before


def test_adoption_outside_every_project_stays_projectless(conn, tmp_path):
    folder = tmp_path / "stray"
    folder.mkdir()
    binding = resolve_project_binding(conn, str(folder), allow_create=False)
    assert binding.rule == BINDING_NONE and binding.project_id is None and _count(conn) == 0
