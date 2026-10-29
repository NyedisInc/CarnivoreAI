
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "roundtrip_lib" / "probe_install.py"


@pytest.fixture()
def probe():
    spec = importlib.util.spec_from_file_location("probe_install_under_test", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def old_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "src.core.db", types.ModuleType("src.core.db"))


def _db(path: Path, column: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE projects (id INTEGER PRIMARY KEY, {column} TEXT NOT NULL)")
    conn.execute("INSERT INTO projects (" + column + ") VALUES ('alpha')")
    conn.commit()
    conn.close()


def test_an_old_tag_is_probed_at_cloude_db(probe, old_install, tmp_path: Path) -> None:
    _db(tmp_path / "cloude.db", "display_name")
    out: dict = {}
    probe.probe_db(tmp_path, out)
    assert out["db_path"].endswith("cloude.db")
    assert out["db_exists"] is True


@pytest.mark.parametrize("column", ["display_name", "name"])
def test_project_names_come_from_the_column_the_table_has(probe, old_install, tmp_path: Path, column: str) -> None:
    _db(tmp_path / "cloude.db", column)
    out: dict = {}
    probe.probe_db(tmp_path, out)
    assert out["db_projects"] == ["alpha"]


def test_a_missing_db_is_not_supported_not_a_crash(probe, old_install, tmp_path: Path) -> None:
    out: dict = {}
    probe.probe_db(tmp_path, out)
    assert out["db_exists"] is False
