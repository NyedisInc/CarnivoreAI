
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfgbu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfgbu_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import ui_preferences
from src.core.config_bundle import constants
from src.core.config_bundle.merge import carry_secrets, deep_merge, diff
from src.core.config_bundle.redact import is_secret_name, redact


def test_redact_drops_by_name_and_by_shape_but_keeps_numbers_and_empties():
    cleaned, dropped = redact(
        {
            "refresh_token_ttl_seconds": 60,
            "api_key": "x",
            "empty_token": "",
            "url": "https://user:pw@example.com/a",
            "hook": "https://hooks.slack.com/services/T/B/x",
            "ok": "plain",
            "nested": [{"password": "p", "keep": 1}],
        },
        "c",
    )
    assert cleaned == {
        "refresh_token_ttl_seconds": 60,
        "empty_token": "",
        "ok": "plain",
        "nested": [{"keep": 1}],
    }
    assert dropped == ["c.api_key", "c.hook", "c.nested[0].password", "c.url"]


def test_no_typed_preference_field_is_mistaken_for_a_secret():
    assert [n for n in ui_preferences.known_fields() if is_secret_name(n)] == []


def test_the_allowlist_never_names_a_credential_block():
    assert not [s for s in constants.EXPORTED_SECTIONS if s in ("totp_secret", "jwt_secret", "server_prefs")]


def test_deep_merge_merges_dicts_and_replaces_lists():
    assert deep_merge({"a": 1, "b": {"c": 2}, "l": [1, 2]}, {"b": {"d": 3}, "l": [9]}) == {
        "a": 1,
        "b": {"c": 2, "d": 3},
        "l": [9],
    }


def test_carry_secrets_restores_local_values_and_matches_lists_by_id():
    existing = {"env": {"api_key": "local"}, "w": [{"id": "a", "token": "t"}, {"id": "b"}]}
    final = {"env": {}, "w": [{"id": "a"}, {"id": "c"}]}
    assert carry_secrets(existing, final) == {
        "env": {"api_key": "local"},
        "w": [{"id": "a", "token": "t"}, {"id": "c"}],
    }


def test_diff_reports_added_changed_removed_and_truncates(monkeypatch):
    result = diff({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "d": 4})
    assert result["counts"] == {"added": 1, "changed": 1, "removed": 1}
    assert [c["kind"] for c in result["changes"]] == ["changed", "removed", "added"]
    monkeypatch.setattr(constants, "MAX_DIFF_ENTRIES", 1)
    assert diff({}, {"a": 1, "b": 2})["truncated"] is True
