
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cfgdef_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cfgdef_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.config_defaults import (
    OPTIONAL_KEYS,
    effective_shipped_defaults,
    shipped_defaults,
    supported_keys,
)
from src.core.config_merge import (
    CANNOT_DETERMINE,
    REMOVED_UPSTREAM,
    merge_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

REGRESSION_KEYS = ("config_version",)


def _merge_like_the_tool(mine: dict, example: dict, base: dict | None = None):
    effective = effective_shipped_defaults(example, mine)
    stale = frozenset(k for k in effective if k not in example)
    return merge_config(
        mine,
        effective,
        base,
        supported_keys=supported_keys(),
        stale_roots=stale,
    )


class TestTheReportedDefect:

    @pytest.mark.parametrize("key", REGRESSION_KEYS)
    def test_live_key_absent_from_example_is_not_called_removed(self, key):
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        assert key not in example, (
            f"{key} is now in config.example.json, so this test no longer "
            "exercises the stale-example path it was written for. Confirm the "
            "merge still handles a stale example before deleting it."
        )

        mine = dict(example)
        mine[key] = shipped_defaults()[key]

        result = _merge_like_the_tool(mine, example)
        outcomes = {d.path: d.outcome for d in result.decisions}
        assert outcomes[key] != REMOVED_UPSTREAM

    @pytest.mark.parametrize("key", REGRESSION_KEYS)
    def test_live_key_at_the_shipped_default_needs_no_attention(self, key):
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        mine = dict(example)
        mine[key] = shipped_defaults()[key]

        result = _merge_like_the_tool(mine, example)
        flagged = {d.path for d in result.needing_attention()}
        assert key not in flagged

    @pytest.mark.parametrize("key", REGRESSION_KEYS)
    def test_the_users_value_is_never_discarded(self, key):
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        mine = dict(example)
        sentinel = 4 if key == "config_version" else [{"label": "x", "command": "x"}]
        mine[key] = sentinel

        result = _merge_like_the_tool(mine, example)
        assert result.merged[key] == sentinel


class TestRemovalRequiresEvidence:

    def test_key_the_loader_does_not_read_is_reported_removed(self):
        example = {"agents": {}}
        mine = {"agents": {}, "a_setting_no_version_ever_had": 1}

        result = _merge_like_the_tool(mine, example)
        outcomes = {d.path: d.outcome for d in result.decisions}
        assert outcomes["a_setting_no_version_ever_had"] == REMOVED_UPSTREAM

    def test_child_of_a_model_filled_subtree_is_cannot_determine(self):
        example = {"agents": {}}
        mine = {"agents": {}, "session": {"a_child": 1}}

        result = _merge_like_the_tool(mine, example)
        outcomes = {d.path: d.outcome for d in result.decisions}
        assert outcomes["session.a_child"] == CANNOT_DETERMINE

    def test_complete_defaults_still_allow_a_removal_verdict(self):
        result = merge_config({"gone": 1}, {}, None)
        assert result.decisions[0].outcome == REMOVED_UPSTREAM


class TestDefaultsTableTracksTheLoader:

    def test_every_loader_key_is_declared(self):
        import ast

        module = (REPO_ROOT / "src" / "config" / "auth_loader.py").read_text()
        tree = ast.parse(module)
        loader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "load"
        )
        source = ast.unparse(loader)

        read_keys = set(re.findall(r'data\.get\(\s*\'([a-z_]+)\'', source))

        declared = supported_keys()
        missing = sorted(read_keys - declared)
        assert not missing, (
            "the auth_loader reads these keys but "
            "src/core/config_defaults.py does not declare them, which is "
            f"exactly the drift that caused the original defect: {missing}"
        )

    def test_optional_keys_carry_no_invented_default(self):
        for key in OPTIONAL_KEYS:
            assert key not in shipped_defaults()
            assert key in supported_keys()

    def test_defaults_are_not_shared_between_calls(self):
        first = shipped_defaults()
        first["projects"].append({"label": "poison"})
        assert not any(
            entry.get("label") == "poison"
            for entry in shipped_defaults()["projects"]
        )

    def test_scalar_defaults_agree_with_the_pydantic_model(self):
        from src.config import AuthConfig

        table = shipped_defaults()
        for name in (
            "config_version",
            "jwt_expiry_minutes",
            "access_token_ttl_seconds",
            "refresh_token_ttl_seconds",
            "refresh_grace_seconds",
        ):
            model_default = AuthConfig.model_fields[name].get_default(
                call_default_factory=True
            )
            assert table[name] == model_default, name


class TestExamplePrecedence:

    def test_example_value_beats_the_model_default(self):
        example = {"jwt_expiry_minutes": 45}
        effective = effective_shipped_defaults(example, {"jwt_expiry_minutes": 1})
        assert effective["jwt_expiry_minutes"] == 45

    def test_model_only_fills_keys_the_user_actually_has(self):
        effective = effective_shipped_defaults({"agents": {}}, {"agents": {}})
        assert "refresh_grace_seconds" not in effective

    def test_effective_defaults_never_alias_their_inputs(self):
        example = {"agents": {"nested": [1]}}
        effective = effective_shipped_defaults(example, {"agents": {}})
        effective["agents"]["nested"].append(2)
        assert example["agents"]["nested"] == [1]


class TestTheCommandLineToolEndToEnd:

    def test_dry_run_on_a_stale_example_reports_no_removals(self, tmp_path):
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        mine = dict(example)
        for key in REGRESSION_KEYS:
            mine[key] = shipped_defaults()[key]

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(mine, indent=2))

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "config_upgrade.py"),
                "--config",
                str(config_path),
                "--state-dir",
                str(tmp_path / "state"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert "REMOVED UPSTREAM" not in proc.stdout, proc.stdout
        for key in REGRESSION_KEYS:
            assert key not in proc.stdout, proc.stdout

    def test_apply_records_the_effective_base_not_the_raw_example(self, tmp_path):
        example = json.loads((REPO_ROOT / "config.example.json").read_text())
        mine = dict(example)
        mine["config_version"] = 4

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(mine, indent=2))
        state_dir = tmp_path / "state"

        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "config_upgrade.py"),
                "--config",
                str(config_path),
                "--state-dir",
                str(state_dir),
                "--apply",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        base = json.loads((state_dir / "config-base.json").read_text())
        assert "config_version" in base

        second = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "config_upgrade.py"),
                "--config",
                str(config_path),
                "--state-dir",
                str(state_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "CANNOT DETERMINE  config_version" not in second.stdout, second.stdout
