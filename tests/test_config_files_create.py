from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import config_files as cf
from src.core import config_files_create as cfc


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-claude-home"
    home.mkdir()
    monkeypatch.setattr(cf, "CLAUDE_HOME", home)
    return home



def test_create_rejects_dot_dot_traversal(fake_home, tmp_path):
    outside = tmp_path / "escaped.md"
    with pytest.raises(cf.ConfigFileError):
        cfc.create_file("user", "../escaped.md", "x", None)
    assert not outside.exists()
    assert list(fake_home.iterdir()) == []


def test_create_rejects_absolute_path(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "/etc/passwd", "x", None)
    assert "absolute" in str(exc.value).lower()
    assert list(fake_home.iterdir()) == []


def test_create_refuses_to_overwrite_an_existing_file(fake_home):
    target = fake_home / "CLAUDE.md"
    target.write_text("original\n")

    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "CLAUDE.md", "replacement\n", None)

    assert "already exists" in str(exc.value)
    assert target.read_text() == "original\n"


def test_create_writes_a_new_file(fake_home):
    result = cfc.create_file("user", "CLAUDE.md", "# hello\n", None)

    assert result["created"] is True
    assert result["rel_path"] == "CLAUDE.md"
    assert (fake_home / "CLAUDE.md").read_text() == "# hello\n"


def test_create_inside_an_existing_nested_directory(fake_home):
    (fake_home / "skills").mkdir()
    (fake_home / "skills" / "deploy").mkdir()

    result = cfc.create_file("user", "skills/deploy/SKILL.md", "body\n", None)

    assert result["rel_path"] == "skills/deploy/SKILL.md"
    assert (fake_home / "skills" / "deploy" / "SKILL.md").read_text() == "body\n"



def test_create_refuses_a_missing_parent_directory(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "skills/brand-new/SKILL.md", "body\n", None)

    message = str(exc.value)
    assert "does not exist" in message
    assert "does not make directories" in message
    assert not (fake_home / "skills").exists()



def test_create_refuses_a_disallowed_top_level_name(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "not-a-config-thing/x.md", "x", None)
    assert "not an allowed" in str(exc.value)


def test_create_refuses_an_empty_path(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "   ", "x", None)
    assert "file name is required" in str(exc.value)


def test_create_refuses_a_hidden_state_entry(fake_home):
    with pytest.raises(cf.ConfigFileError):
        cfc.create_file("user", "projects/sneaky.md", "x", None)


def test_create_of_an_executable_needs_acknowledgement(fake_home):
    (fake_home / "hooks").mkdir()

    with pytest.raises(cfc.ConfirmationRequiredError) as exc:
        cfc.create_file("user", "hooks/new-guard.py", "print(1)\n", None)
    assert "confirmation" in str(exc.value)
    assert exc.value.acknowledge == cfc.CONFIRM_EXECUTABLE
    assert not (fake_home / "hooks" / "new-guard.py").exists()

    result = cfc.create_file(
        "user", "hooks/new-guard.py", "print(1)\n", None,
        acknowledge_executable=True,
    )
    assert result["is_executable"] is True
    assert (fake_home / "hooks" / "new-guard.py").read_text() == "print(1)\n"


def test_create_of_a_sensitive_name_needs_acknowledgement(fake_home):
    with pytest.raises(cfc.ConfirmationRequiredError) as exc:
        cfc.create_file("user", ".credentials.json", "{}", None)
    assert "confirmation" in str(exc.value)
    assert exc.value.acknowledge == cfc.CONFIRM_SENSITIVE

    result = cfc.create_file(
        "user", ".credentials.json", "{}", None,
        acknowledge_sensitive=True,
    )
    assert result["is_sensitive"] is True


def test_create_validates_json_before_touching_disk(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "settings.json", "{not json", None)
    assert "invalid json" in str(exc.value)
    assert not (fake_home / "settings.json").exists()

    cfc.create_file("user", "settings.json", '{"a": 1}', None)
    assert json.loads((fake_home / "settings.json").read_text()) == {"a": 1}


def test_create_refuses_a_read_only_root(fake_home):
    (fake_home / "plugins").mkdir()
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "plugins/thing.md", "x", None)
    assert "read-only" in str(exc.value)


def test_create_refuses_to_replace_a_directory(fake_home):
    (fake_home / "skills").mkdir()
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "skills", "x", None)
    assert "already exists" in str(exc.value)
    assert (fake_home / "skills").is_dir()


def test_create_in_workdir_root_has_no_allowlist_but_keeps_containment(tmp_path, fake_home):
    workdir = tmp_path / "project"
    workdir.mkdir()

    result = cfc.create_file("workdir", "anything.txt", "hi\n", str(workdir))
    assert (workdir / "anything.txt").read_text() == "hi\n"
    assert result["created"] is True

    with pytest.raises(cf.ConfigFileError):
        cfc.create_file("workdir", "../outside.txt", "x", str(workdir))
    assert not (tmp_path / "outside.txt").exists()


def test_create_error_message_does_not_leak_an_absolute_path(fake_home):
    with pytest.raises(cf.ConfigFileError) as exc:
        cfc.create_file("user", "skills/nope/SKILL.md", "x", None)
    assert str(fake_home) not in str(exc.value)
