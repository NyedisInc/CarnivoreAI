
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ctr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ctr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.catalog.token_refresh import (
    ACCESS_SKEW_SECONDS,
    ROTATE,
    SIGNED_OUT,
    USE_ACCESS,
    session_from_refresh,
    token_action,
)
from src.core.catalog.token_store import CatalogSession

NOW = 1_800_000_000


def _session(*, access_in: int, refresh_in: int, login: str = "example-owner") -> CatalogSession:
    return CatalogSession(
        login=login,
        access_token="ACCESS-TOKEN-SECRET",
        access_expires_at=NOW + access_in,
        refresh_token="REFRESH-TOKEN-SECRET",
        refresh_expires_at=NOW + refresh_in,
    )


class TestWhichOfTheThreeThingsToDo:

    def test_a_live_access_token_is_simply_used(self):
        held = _session(access_in=3600, refresh_in=86400)
        assert token_action(held, NOW) == USE_ACCESS

    def test_an_expired_access_token_with_a_live_refresh_ROTATES(self):
        held = _session(access_in=-10, refresh_in=86400)
        assert token_action(held, NOW) == ROTATE

    def test_both_expired_is_signed_out(self):
        held = _session(access_in=-10, refresh_in=-10)
        assert token_action(held, NOW) == SIGNED_OUT

    def test_nothing_held_at_all_is_signed_out(self):
        assert token_action(None, NOW) == SIGNED_OUT

    def test_a_token_expiring_INSIDE_the_skew_rotates_rather_than_racing(self):
        held = _session(access_in=ACCESS_SKEW_SECONDS - 1, refresh_in=86400)
        assert token_action(held, NOW) == ROTATE

    def test_NEGATIVE_CONTROL_just_outside_the_skew_is_still_used(self):
        held = _session(access_in=ACCESS_SKEW_SECONDS + 60, refresh_in=86400)
        assert token_action(held, NOW) == USE_ACCESS

    def test_an_expired_access_and_an_expiring_refresh_is_signed_out(self):
        held = _session(access_in=-10, refresh_in=ACCESS_SKEW_SECONDS - 1)
        assert token_action(held, NOW) == SIGNED_OUT


class TestReadingWhatTheHostRotatedTo:

    def test_a_whole_answer_becomes_the_replacement_session(self):
        replacement = session_from_refresh(
            {
                "access_token": "NEW-ACCESS",
                "expires_in": 28800,
                "refresh_token": "NEW-REFRESH",
                "refresh_expires_in": 2592000,
                "login": "example-owner",
            },
            fallback_login="example-owner",
            now=NOW,
        )
        assert replacement is not None
        assert replacement.access_token == "NEW-ACCESS"
        assert replacement.refresh_token == "NEW-REFRESH"
        assert replacement.access_expires_at == NOW + 28800
        assert replacement.refresh_expires_at == NOW + 2592000
        assert replacement.login == "example-owner"

    def test_an_answer_with_NO_access_token_is_refused_rather_than_stored(self):
        assert session_from_refresh(
            {"refresh_token": "NEW-REFRESH", "expires_in": 28800},
            fallback_login="example-owner",
            now=NOW,
        ) is None

    def test_an_answer_with_NO_refresh_token_is_refused_too(self):
        assert session_from_refresh(
            {"access_token": "NEW-ACCESS", "expires_in": 28800},
            fallback_login="example-owner",
            now=NOW,
        ) is None

    def test_a_login_the_answer_omitted_falls_back_to_the_one_held(self):
        replacement = session_from_refresh(
            {
                "access_token": "NEW-ACCESS",
                "expires_in": 28800,
                "refresh_token": "NEW-REFRESH",
                "refresh_expires_in": 2592000,
            },
            fallback_login="example-owner",
            now=NOW,
        )
        assert replacement is not None
        assert replacement.login == "example-owner"
