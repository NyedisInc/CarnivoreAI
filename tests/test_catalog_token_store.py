
from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cts_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cts_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.token_store import (
    CatalogSession,
    open_token_store,
    token_db_path,
)


def a_session(**overrides) -> CatalogSession:
    fields = {
        "login": "example-owner",
        "access_token": "access-token-value",
        "access_expires_at": 2_000_000_000,
        "refresh_token": "refresh-token-value",
        "refresh_expires_at": 2_100_000_000,
    }
    fields.update(overrides)
    return CatalogSession(**fields)


def test_a_store_that_was_never_written_reads_as_absent(tmp_path):
    with open_token_store(tmp_path) as store:
        assert store.read() is None


def test_a_saved_session_reads_back_field_for_field(tmp_path):
    with open_token_store(tmp_path) as store:
        store.save(a_session())
    with open_token_store(tmp_path) as store:
        held = store.read()
    assert held == a_session()


def test_a_second_sign_in_REPLACES_the_first(tmp_path):
    with open_token_store(tmp_path) as store:
        store.save(a_session(login="first", access_token="first-token"))
        store.save(a_session(login="second", access_token="second-token"))
        held = store.read()
    assert held is not None
    assert held.login == "second"
    assert held.access_token == "second-token"


def test_clearing_removes_the_bytes_and_not_only_the_answer(tmp_path):
    with open_token_store(tmp_path) as store:
        store.save(a_session())
        store.clear()
        assert store.read() is None
    raw = token_db_path(tmp_path).read_bytes()
    assert b"access-token-value" not in raw
    assert b"refresh-token-value" not in raw


def test_the_paired_positive_that_the_file_really_would_hold_it(tmp_path):
    with open_token_store(tmp_path) as store:
        store.save(a_session())
    assert b"access-token-value" in token_db_path(tmp_path).read_bytes()


@pytest.mark.skipif(os.name == "nt", reason="posix permission bits")
def test_the_file_is_not_readable_by_anybody_else(tmp_path):
    with open_token_store(tmp_path) as store:
        store.save(a_session())
    mode = stat.S_IMODE(token_db_path(tmp_path).stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_the_database_is_its_own_file_and_not_cloude_db(tmp_path):
    assert token_db_path(tmp_path).name != "cloude.db"
    assert token_db_path(tmp_path).parent == tmp_path


def test_the_sign_in_log_line_holds_no_email_or_login(tmp_path):
    from structlog.testing import capture_logs

    with open_token_store(tmp_path) as store, capture_logs() as logs:
        store.save(a_session(login="someone@example.com", provider="google"))
    stored = [e for e in logs if e["event"] == "catalog_signin_stored"]
    assert stored and all(e.get("provider") == "google" for e in stored)
    assert "someone@example.com" not in repr(logs) and not any("login" in e for e in logs)
