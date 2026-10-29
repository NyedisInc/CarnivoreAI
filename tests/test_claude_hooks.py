from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ch_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ch_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import claude_hooks
from src.core.claude_hooks import (
    CLOUDECODE_HOOKS_MARKER,
    _is_managed_command,
    strip_managed_hooks,
)




def _managed_entry(event: str = "Stop") -> dict:
    return {
        "matcher": "*",
        "hooks": [
            {
                "type": "command",
                "command": (
                    f'(cat | curl -sS -m 2 -X POST "$CLOUDECODE_HOOK_URL" '
                    f'-H "X-Cloudecode-Event: {event}" --data-binary @-) '
                    f"> /dev/null 2>&1 ; : {CLOUDECODE_HOOKS_MARKER}"
                ),
            }
        ],
    }


def _user_entry(command: str = "echo mine") -> dict:
    return {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": command}],
    }


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(claude_hooks.SETTINGS_PATH_ENV_VAR, str(path))
    return path


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))




def test_a_missing_settings_file_is_left_missing(settings_file):
    assert strip_managed_hooks(settings_file) is True
    assert not settings_file.exists()


def test_a_file_with_no_hooks_key_is_untouched(settings_file):
    _write(settings_file, {"model": "opus", "theme": "dark"})
    before = settings_file.read_text(encoding="utf-8")
    mtime = settings_file.stat().st_mtime_ns

    assert strip_managed_hooks(settings_file) is True

    assert settings_file.read_text(encoding="utf-8") == before
    assert settings_file.stat().st_mtime_ns == mtime


def test_a_file_holding_only_user_hooks_is_untouched(settings_file):
    doc = {"hooks": {"PreToolUse": [_user_entry()], "Stop": [_user_entry("ls")]}}
    _write(settings_file, doc)
    mtime = settings_file.stat().st_mtime_ns

    assert strip_managed_hooks(settings_file) is True

    assert _read(settings_file) == doc
    assert settings_file.stat().st_mtime_ns == mtime


def test_the_strip_is_idempotent(settings_file):
    _write(settings_file, {"hooks": {"Stop": [_managed_entry()]}})
    assert strip_managed_hooks(settings_file) is True
    after_first = settings_file.read_text(encoding="utf-8")
    mtime = settings_file.stat().st_mtime_ns

    assert strip_managed_hooks(settings_file) is True

    assert settings_file.read_text(encoding="utf-8") == after_first
    assert settings_file.stat().st_mtime_ns == mtime




def test_a_whole_managed_block_is_removed_down_to_the_hooks_key(settings_file):
    events = [
        "Stop",
        "Notification",
        "PermissionRequest",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
        "SessionStart",
        "SessionEnd",
    ]
    _write(
        settings_file,
        {
            "model": "opus",
            "hooks": {event: [_managed_entry(event)] for event in events},
        },
    )

    assert strip_managed_hooks(settings_file) is True

    doc = _read(settings_file)
    assert "hooks" not in doc
    assert doc == {"model": "opus"}
    assert CLOUDECODE_HOOKS_MARKER not in settings_file.read_text(encoding="utf-8")


def test_a_user_hook_survives_beside_a_removed_managed_one(settings_file):
    mine = _user_entry("say-done")
    _write(
        settings_file,
        {
            "hooks": {
                "Stop": [mine, _managed_entry("Stop")],
                "PreToolUse": [_managed_entry("PreToolUse")],
            }
        },
    )

    assert strip_managed_hooks(settings_file) is True

    doc = _read(settings_file)
    assert doc == {"hooks": {"Stop": [mine]}}


def test_an_event_key_the_user_owns_outright_keeps_its_empty_list(settings_file):
    _write(
        settings_file,
        {"hooks": {"Notification": [], "Stop": [_managed_entry()]}},
    )

    assert strip_managed_hooks(settings_file) is True

    assert _read(settings_file) == {"hooks": {"Notification": []}}


def test_a_matcher_shape_we_never_wrote_is_preserved_verbatim(settings_file):
    _write(
        settings_file,
        {
            "hooks": {
                "Weird": {"not": "a list"},
                "AlsoWeird": ["a bare string", 7],
                "Stop": [_managed_entry()],
            }
        },
    )

    assert strip_managed_hooks(settings_file) is True

    assert _read(settings_file) == {
        "hooks": {"Weird": {"not": "a list"}, "AlsoWeird": ["a bare string", 7]}
    }


def test_a_mixed_matcher_entry_is_dropped_whole(settings_file):
    mixed = {
        "matcher": "*",
        "hooks": [
            {"type": "command", "command": "echo first"},
            _managed_entry()["hooks"][0],
        ],
    }
    mine = _user_entry("echo untouched")
    _write(settings_file, {"hooks": {"Stop": [mixed, mine]}})

    assert strip_managed_hooks(settings_file) is True

    assert _read(settings_file) == {"hooks": {"Stop": [mine]}}




def test_unparseable_json_bails_without_clobbering(settings_file):
    settings_file.write_text('{"hooks": {"Stop": [', encoding="utf-8")
    before = settings_file.read_text(encoding="utf-8")

    assert strip_managed_hooks(settings_file) is False

    assert settings_file.read_text(encoding="utf-8") == before


def test_a_top_level_non_object_bails_without_clobbering(settings_file):
    settings_file.write_text("[1, 2, 3]", encoding="utf-8")

    assert strip_managed_hooks(settings_file) is False

    assert settings_file.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_an_empty_file_is_a_no_op_success(settings_file):
    settings_file.write_text("   \n", encoding="utf-8")

    assert strip_managed_hooks(settings_file) is True

    assert settings_file.read_text(encoding="utf-8") == "   \n"


def test_a_hooks_value_of_the_wrong_type_is_left_alone(settings_file):
    _write(settings_file, {"hooks": "surprise"})

    assert strip_managed_hooks(settings_file) is True

    assert _read(settings_file) == {"hooks": "surprise"}




def test_default_settings_path_honours_the_override(settings_file, monkeypatch):
    assert claude_hooks.default_settings_path() == settings_file


def test_default_settings_path_falls_back_to_the_home_file(monkeypatch):
    monkeypatch.delenv(claude_hooks.SETTINGS_PATH_ENV_VAR, raising=False)
    assert claude_hooks.default_settings_path() == (
        Path.home() / ".claude" / "settings.json"
    )


def test_the_write_guard_refuses_a_destination_outside_tmp(tmp_path):
    from src.core.test_write_guard import OutsideTempWriteError

    with pytest.raises(OutsideTempWriteError):
        strip_managed_hooks(Path("/definitely/not/tmp/settings.json"))




def test_the_marker_identifies_only_our_own_commands():
    assert _is_managed_command(f"curl ... ; : {CLOUDECODE_HOOKS_MARKER}") is True
    assert _is_managed_command("echo mine") is False


@pytest.mark.parametrize("value", [None, 7, {"nested": True}, ["list"]])
def test_a_non_string_command_is_not_ours_and_does_not_raise(value):
    assert _is_managed_command(value) is False




@pytest.mark.parametrize(
    "name",
    [
        "ensure_hook_settings",
        "_build_hook_block",
        "_build_managed_command",
        "_merge_hooks",
        "_MANAGED_EVENTS",
        "_hooks_disabled",
    ],
)
def test_the_module_exports_no_installer(name):
    assert not hasattr(claude_hooks, name), (
        f"claude_hooks.{name} is back; the hook installer was deleted on "
        f"2026-09-13 and nothing may reinstate it without a decision"
    )


def test_the_opt_out_setting_is_gone_from_the_config_model():
    from src.config.auth import AuthConfig

    assert "notifications" not in AuthConfig.model_fields
