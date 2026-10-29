
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.account_notice import runner
from src.core.app_alerts import conditions
from src.core.catalog import catalog_auth
from src.core.db import db_path_for


@pytest.fixture()
def state(tmp_path: Path, monkeypatch):
    box = SimpleNamespace(tmux_session=None, session=None)
    monkeypatch.setattr(catalog_auth, "read_session", lambda _dir: box.session)
    runner.install(tmp_path, pairing=lambda: box.pairing)
    box.pairing = None
    box.dir = tmp_path
    yield box
    runner.uninstall()


def _share_row(state_dir: Path) -> None:
    with sqlite3.connect(db_path_for(state_dir)) as conn:
        conn.execute("CREATE TABLE spectator_links (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO spectator_links VALUES ('l1')")


def test_signed_out_with_hosted_history_is_active(state):
    state.pairing = SimpleNamespace(enabled=True, device_count=lambda: 0)
    assert isinstance(runner.probe(), conditions.Active)


def test_a_share_link_minted_before_counts_as_history(state):
    _share_row(state.dir)
    assert isinstance(runner.probe(), conditions.Active)


def test_signed_in_is_clear(state):
    state.pairing = SimpleNamespace(enabled=True, device_count=lambda: 2)
    state.session = object()
    assert runner.probe() is conditions.CLEAR


def test_signed_out_with_no_history_is_clear(state):
    state.pairing = SimpleNamespace(enabled=False, device_count=lambda: 0)
    assert runner.probe() is conditions.CLEAR
