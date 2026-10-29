
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import Settings
from src.core.agent_families import resolve_agent_type
from src.core.sessions import wrapper_source


def test_settings_has_no_agents_attribute():
    from src.config import settings

    assert not hasattr(settings, "agents"), (
        "Settings grew an 'agents' attribute; the wrapper-lookup helper and "
        "this test both assume the config path is load_auth_config().agents"
    )


def test_the_helper_reads_the_real_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "config_version": 3,
        "agents": {
            "claude_command": "",
            "wrappers": [{
                "id": "claude-skip-permissions",
                "label": "claude",
                "script": "claude --dangerously-skip-permissions",
                "default": True,
                "family": "claude",
            }],
        },
        "projects": [],
    }))
    patched = Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x", jwt_secret="y",
        auth_config_file=str(config_path),
    )
    got = wrapper_source.configured_wrappers(settings_provider=lambda: patched)
    assert [w.id for w in got] == ["claude-skip-permissions"], (
        "the helper did not read the configured wrappers"
    )


def test_a_wrapper_id_resolves_to_its_family(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "config_version": 3,
        "agents": {
            "claude_command": "",
            "wrappers": [{
                "id": "claude-skip-permissions", "label": "claude",
                "script": "claude --dangerously-skip-permissions",
                "default": True, "family": "claude",
            }],
        },
        "projects": [],
    }))
    patched = Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x", jwt_secret="y",
        auth_config_file=str(config_path),
    )
    family, explicit = resolve_agent_type(
        "claude-skip-permissions",
        wrapper_source.configured_wrappers(settings_provider=lambda: patched),
    )
    assert family.name == "claude"
    assert explicit is not None and explicit.id == "claude-skip-permissions"


def test_an_unreadable_config_degrades_to_empty_not_an_exception(tmp_path):
    patched = Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x", jwt_secret="y",
        auth_config_file=str(tmp_path / "does-not-exist.json"),
    )
    assert wrapper_source.configured_wrappers(settings_provider=lambda: patched) == []


def test_no_call_site_uses_the_old_broken_chain():
    import ast

    offenders = []
    for rel in ("src/core/session_manager.py", "src/api/session_crud_routes.py"):
        tree = ast.parse((ROOT / rel).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Name) and fn.id == "getattr"):
                continue
            if len(node.args) < 2:
                continue
            target, attr = node.args[0], node.args[1]
            is_settings = isinstance(target, ast.Name) and target.id == "settings"
            is_agents = isinstance(attr, ast.Constant) and attr.value == "agents"
            if is_settings and is_agents:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"the wrong wrapper-lookup path is back at {offenders}; "
        "use sessions.wrapper_source.configured_wrappers()"
    )
