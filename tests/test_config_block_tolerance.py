
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cbt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cbt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.auth_loader import load, parse_block
from src.config.session import SessionConfig
from src.config.ui import UIConfig
from src.config.workspace import WorkspaceConfig

GARBAGE = ["not", "a", "mapping"]


def _config(tmp_path: Path, **blocks) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_version": 1, **blocks}))
    return path


def _load(path: Path):
    return load(path, totp_secret="t" * 16, jwt_secret="j" * 16)




def test_a_valid_block_round_trips_its_values():
    parsed = parse_block(
        SessionConfig, {"disable_alternate_screen": True}, event="unused"
    )

    assert parsed.disable_alternate_screen is True


def test_a_mangled_block_becomes_defaults_and_says_so():
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        parsed = parse_block(
            SessionConfig, GARBAGE, event="invalid_session_config_block"
        )

    assert parsed == SessionConfig()
    assert [e for e in logs if e["event"] == "invalid_session_config_block"]


def test_a_workspace_rejection_logs_key_names_and_never_a_value():
    from structlog.testing import capture_logs

    from src.config.auth_loader import _keys_only_payload

    with capture_logs() as logs:
        parse_block(
            WorkspaceConfig,
            {"env": "hunter2-this-is-the-secret"},
            event="invalid_workspace_config_block",
            payload=_keys_only_payload,
        )

    rejections = [
        e for e in logs if e["event"] == "invalid_workspace_config_block"
    ]
    assert rejections
    assert "hunter2-this-is-the-secret" not in repr(rejections), (
        "a workspace value reached the log; that value can be a secret"
    )
    assert rejections[0]["keys"] == ["env"]




@pytest.mark.parametrize(
    "key,attribute",
    [
        ("session", "session"),
        ("auth_rate_limits", "auth_rate_limits"),
        ("agents", "agents"),
        ("uploads", "uploads"),
        ("providers", "providers"),
        ("workspace", "workspace"),
        ("server_prefs", "server_prefs"),
        ("ui", "ui"),
    ],
)
def test_one_mangled_block_costs_only_that_block(tmp_path, key, attribute):
    path = _config(tmp_path, **{key: GARBAGE}, template_path="/tmp/marker")

    config = _load(path)

    assert getattr(config, attribute) is not None
    assert config.template_path == "/tmp/marker", (
        f"a mangled {key!r} block took the rest of the config with it"
    )


def test_a_legacy_notifications_block_is_ignored_not_fatal(tmp_path):
    config = _load(_config(tmp_path, notifications=GARBAGE, template_path="/tmp/marker"))

    assert not hasattr(config, "notifications")
    assert config.template_path == "/tmp/marker"


@pytest.mark.parametrize("old_block", [GARBAGE, {"enabled": True}, {"enabled": False}])
def test_an_old_message_archive_key_is_ignored_cleanly(tmp_path, old_block):
    config = _load(_config(tmp_path, message_archive=old_block, template_path="/tmp/marker"))

    assert not hasattr(config, "message_archive")
    assert config.template_path == "/tmp/marker"


def test_a_mangled_ui_block_cannot_hide_a_capability(tmp_path):
    config = _load(_config(tmp_path, ui=GARBAGE))

    assert config.ui == UIConfig()




def test_a_missing_file_is_refused_not_tolerated(tmp_path):
    with pytest.raises(FileNotFoundError):
        _load(tmp_path / "nope.json")


def test_invalid_json_is_refused_and_names_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json")

    with pytest.raises(ValueError) as caught:
        _load(path)

    assert str(path) in str(caught.value)


def test_a_missing_secret_is_refused(tmp_path):
    with pytest.raises(ValueError):
        load(_config(tmp_path), totp_secret=None, jwt_secret="j" * 16)
