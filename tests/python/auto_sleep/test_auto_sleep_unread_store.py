
from __future__ import annotations

import json
import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_asu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_asu_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config.auto_sleep import AutoSleepConfig
from src.core.auto_sleep import store


def test_defaults_do_not_hold_an_unread_session_awake():
    cfg = AutoSleepConfig()
    assert cfg.unread_blocks_sleep is False and cfg.unread_idle_minutes == cfg.idle_minutes == 60


def test_an_old_block_without_the_fields_reads_the_defaults():
    cfg = store.read_block({"auto_sleep": {"enabled": True, "idle_minutes": 30}})
    assert cfg.unread_blocks_sleep is False and cfg.unread_idle_minutes == 60


def test_set_settings_merges_and_leaves_keep_awake_alone(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"auto_sleep": {"keep_awake": ["abc12345"]}, "other": 1}))
    store.set_settings(path, unread_blocks_sleep=False, unread_idle_minutes=200)
    doc = json.loads(path.read_text())
    assert doc["other"] == 1
    assert doc["auto_sleep"]["keep_awake"] == ["abc12345"]
    assert doc["auto_sleep"]["unread_blocks_sleep"] is False
    assert doc["auto_sleep"]["unread_idle_minutes"] == 200


def test_unread_idle_minutes_below_the_floor_is_refused(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        store.set_settings(path, unread_idle_minutes=1)
