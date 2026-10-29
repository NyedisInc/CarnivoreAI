
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("CLOUDE_STATE_DIR", tempfile.mkdtemp(prefix="cc_uiflags_state_"))
os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_uiflags_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_uiflags_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import AuthConfig, Settings, UIConfig


def test_the_control_is_shown_by_default():
    assert UIConfig().show_mark_unread_control is True


def test_a_config_with_no_ui_key_still_shows_the_control():
    cfg = AuthConfig()
    assert "ui" not in cfg.model_dump(exclude_unset=True)
    assert cfg.ui.show_mark_unread_control is True


def test_an_explicit_false_round_trips_through_json():
    written = AuthConfig(ui={"show_mark_unread_control": False})
    assert written.ui.show_mark_unread_control is False

    reread = AuthConfig(**json.loads(json.dumps(written.model_dump())))
    assert reread.ui.show_mark_unread_control is False


def test_an_explicit_true_round_trips_too():
    reread = AuthConfig(
        **json.loads(json.dumps(AuthConfig(ui={"show_mark_unread_control": True}).model_dump()))
    )
    assert reread.ui.show_mark_unread_control is True


def test_an_unknown_ui_key_does_not_break_the_load():
    cfg = AuthConfig(ui={"show_mark_unread_control": False, "some_future_flag": True})
    assert cfg.ui.show_mark_unread_control is False


def _settings(tmp_path, ui=None):
    body = {"config_version": 3}
    if ui is not None:
        body["ui"] = ui
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(body))
    return Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x",
        jwt_secret="y",
        auth_config_file=str(config_path),
    )


def test_the_settings_summary_carries_the_block(tmp_path):
    summary = _settings(tmp_path).get_settings_summary()
    assert "ui" in summary
    assert summary["ui"]["show_mark_unread_control"] is True


def test_the_settings_summary_reports_the_stored_value_not_the_default(tmp_path):
    summary = _settings(
        tmp_path, ui={"show_mark_unread_control": False}
    ).get_settings_summary()
    assert summary["ui"]["show_mark_unread_control"] is False


def test_a_config_file_with_no_ui_key_summarises_as_shown(tmp_path):
    summary = _settings(tmp_path, ui=None).get_settings_summary()
    assert summary["ui"]["show_mark_unread_control"] is True


def test_the_client_actually_probes_the_flag():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    client_js = root / "client" / "js"

    for path, marker in (
        (root / "web" / "src" / "lib" / "drawer" / "fetch.ts", "G.UIFlags.ensure"),
        (root / "web" / "src" / "lib" / "sessions" / "store.svelte.ts",
         "flags.ensure"),
    ):
        src = path.read_text(encoding="utf-8")
        assert marker in src, (
            f"{path.name} must probe the UI flags, or the setting never "
            "reaches the client and fails silently"
        )

    index = (client_js.parent / "index.html").read_text(encoding="utf-8")
    assert "/static/js/ui-flags.js" in index
