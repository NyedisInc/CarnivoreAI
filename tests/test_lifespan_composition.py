
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import asyncio  # noqa: E402

from src.core.composition import AppServices  # noqa: E402
from src.main import app  # noqa: E402


@pytest.fixture
def booted():
    with TestClient(app):
        yield app


def test_the_services_container_is_on_app_state(booted):
    assert isinstance(booted.state.services, AppServices)


def test_both_app_state_entries_name_the_same_manager(booted):
    assert booted.state.session_manager is booted.state.services.session_manager


def test_the_collaborators_on_app_state_are_the_manager_s_own(booted):
    services = booted.state.services
    manager = booted.state.session_manager

    assert services.themes is manager._theme_store
    assert services.toasts is manager._toast_inbox

    services.registry.command_counts["ses_booted"] = 4
    assert manager._registry.command_counts["ses_booted"] == 4
    manager._theme_store.pinned_themes["cloude_booted"] = "matrix"
    assert services.themes.pinned_themes["cloude_booted"] == "matrix"


def test_the_interrupted_update_pass_is_scheduled_at_boot(booted):
    task = booted.state.skill_journal_recovery

    assert isinstance(task, asyncio.Task), type(task)
