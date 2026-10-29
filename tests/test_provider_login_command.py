
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger.login_command import login_command_for, login_env_for

CLAUDE = ProviderAccount(id="claude1", name="Claude 1", provider="claude")
CODEX = ProviderAccount(id="codex1", name="Codex 1", provider="codex")


def test_the_claude_line_is_exactly_this() -> None:
    assert login_command_for(CLAUDE, "/Users/a/.carnivore/accounts/claude1") == (
        "CLAUDE_CONFIG_DIR=/Users/a/.carnivore/accounts/claude1 "
        "command claude auth login"
    )


def test_the_claude_line_bypasses_the_zsh_wrapper() -> None:
    line = login_command_for(CLAUDE, "/tmp/p")
    assert " command claude auth login" in line
    assert " claude auth login" not in line.replace(" command claude", " command")


def test_the_claude_line_never_asks_for_a_setup_token() -> None:
    assert "setup-token" not in login_command_for(CLAUDE, "/tmp/p")


def test_the_codex_line_is_exactly_this() -> None:
    assert login_command_for(CODEX, "/Users/a/.carnivore/accounts/codex1") == (
        "CODEX_HOME=/Users/a/.carnivore/accounts/codex1 codex login"
    )


def test_the_codex_line_never_uses_the_device_flag() -> None:
    assert "--device-auth" not in login_command_for(CODEX, "/tmp/p")


def test_a_path_with_a_space_is_quoted() -> None:
    line = login_command_for(CLAUDE, "/tmp/two words/claude1")
    assert "'/tmp/two words/claude1'" in line


def test_an_unknown_provider_raises_rather_than_guessing() -> None:
    rogue = ProviderAccount.model_construct(
        id="x", name="X", provider="gemini", claude_config_dir="~", codex_home="~"
    )
    with pytest.raises(ValueError):
        login_command_for(rogue, "/tmp/p")


def test_the_claude_env_pair_is_the_config_dir() -> None:
    assert login_env_for(CLAUDE, "/tmp/p") == {"CLAUDE_CONFIG_DIR": "/tmp/p"}


def test_the_codex_env_pair_is_the_codex_home() -> None:
    assert login_env_for(CODEX, "/tmp/p") == {"CODEX_HOME": "/tmp/p"}


def test_the_env_pair_carries_the_raw_string_and_never_a_realpath(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    value = login_env_for(CLAUDE, str(link))["CLAUDE_CONFIG_DIR"]
    assert value == str(link)


def test_an_unknown_provider_has_no_env_pair_either() -> None:
    rogue = ProviderAccount.model_construct(
        id="x", name="X", provider="gemini", claude_config_dir="~", codex_home="~"
    )
    with pytest.raises(ValueError):
        login_env_for(rogue, "/tmp/p")


def test_nothing_in_this_module_runs_a_subprocess() -> None:
    import ast

    from src.core.provider_ledger import login_command

    tree = ast.parse(Path(login_command.__file__).read_text())
    imported = set()
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name:
                called.add(name)

    assert "subprocess" not in imported
    assert imported <= {"__future__", "os", "shlex", "typing", "unicodedata", "src"}
    for forbidden in ["system", "popen", "run", "Popen", "eval", "exec"]:
        assert forbidden not in called, forbidden
