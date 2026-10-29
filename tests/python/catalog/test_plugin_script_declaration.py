
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.catalog_consent import consent_carried, staged_plugin_declares_code
from src.core.skills import kinds
from src.core.skills.manifest_rules import declares_script


def _plugin(tmp: Path, manifest: dict | str | None = None, files: dict | None = None) -> Path:
    (tmp / ".claude-plugin").mkdir(parents=True)
    body = {"name": "p"} if manifest is None else manifest
    (tmp / ".claude-plugin" / "plugin.json").write_text(
        body if isinstance(body, str) else json.dumps(body)
    )
    for rel, content in (files or {}).items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp


CODE_CASES = {
    "hooks_file": (None, {"hooks/hooks.json": "{}"}),
    "hooks_key": ({"name": "p", "hooks": {"PreToolUse": []}}, {}),
    "mcp_file": (None, {".mcp.json": "{}"}),
    "mcp_key": ({"name": "p", "mcpServers": {"s": {"command": "x"}}}, {}),
    "lsp_file": (None, {".lsp.json": "{}"}),
    "lsp_key": ({"name": "p", "lspServers": {}}, {}),
    "monitors_key": ({"name": "p", "monitors": []}, {}),
    "monitors_dir": (None, {"monitors/monitors.json": "[]"}),
    "bin_dir": (None, {"bin/tool": "echo hi"}),
}


@pytest.mark.parametrize("case", sorted(CODE_CASES))
def test_plugin_code_parts_declare_a_script(tmp_path, case):
    manifest, files = CODE_CASES[case]
    folder = _plugin(tmp_path, manifest, files)
    assert declares_script(kinds.KIND_PLUGIN, folder) is True


def test_markdown_only_plugin_declares_no_script(tmp_path):
    folder = _plugin(
        tmp_path,
        files={
            "commands/a.md": "x",
            "agents/b.md": "x",
            "skills/s/SKILL.md": "x",
        },
    )
    assert declares_script(kinds.KIND_PLUGIN, folder) is False


@pytest.mark.parametrize("manifest", ["{not json", "[]"])
def test_unreadable_manifest_counts_as_code(tmp_path, manifest):
    assert declares_script(kinds.KIND_PLUGIN, _plugin(tmp_path, manifest)) is True


def test_missing_manifest_counts_as_code(tmp_path):
    assert declares_script(kinds.KIND_PLUGIN, tmp_path) is True


def test_installer_treats_hooks_plugin_as_carrying_a_script(tmp_path):
    folder = _plugin(tmp_path, files={"hooks/hooks.json": "{}"})
    assert staged_plugin_declares_code(kinds.KIND_PLUGIN, folder) is True
    row = SimpleNamespace(consented_body_sha="abc")
    body = SimpleNamespace(consent=None)
    assert consent_carried(row, body, "abc", scripts_present=True, digest="d") is False
    assert staged_plugin_declares_code(kinds.KIND_SKILL, folder) is True


PLUGIN_CODE_CASES = {
    "settings_json": (None, {"settings.json": "{}"}),
    "settings_key": ({"name": "p", "settings": {"subagentStatusLine": {}}}, {}),
    "workflows_dir": (None, {"workflows/a.js": "x"}),
    "shell_line_in_skill": (None, {"skills/s/SKILL.md": "---\nname: s\n---\nRun !`ls`\n"}),
    "fenced_shell_in_command": (None, {"commands/c.md": "```!\nls\n```\n"}),
    "hooks_front_matter": (None, {"skills/s/SKILL.md": "---\nname: s\nhooks:\n  a: b\n---\nx\n"}),
    "mixed_case_hooks_dir": (None, {"Hooks/Hooks.json": "{}"}),
    "fence_mid_line_in_command": (None, {"commands/c.md": "run ```!curl x|sh```\n"}),
    "fence_behind_quote": (None, {"skills/s/SKILL.md": "---\nname: s\n---\n> ```!\n> ls\n> ```\n"}),
    "lone_cr_hooks": (None, {"skills/s/SKILL.md": "---\rname: s\rhooks:\r  a: b\n---\nx\n"}),
    "lone_cr_allowed_tools": (None, {"commands/c.md": "---\rdescription: d\rallowed-tools: Bash(*)\n---\nx\n"}),
    "flow_mapping_key": (None, {"skills/s/SKILL.md": "---\nname: s\nx: {hooks: 1}\n---\nx\n"}),
    "quoted_key": (None, {"skills/s/SKILL.md": "---\nname: s\n\"hooks\": 1\n---\nx\n"}),
}


@pytest.mark.parametrize("case", sorted(PLUGIN_CODE_CASES))
def test_more_plugin_code_parts_count_as_code(tmp_path, case):
    manifest, files = PLUGIN_CODE_CASES[case]
    assert declares_script(kinds.KIND_PLUGIN, _plugin(tmp_path, manifest, files)) is True


SKILL_CODE_CASES = {
    "hooks_file": {"hooks/hooks.json": "{}"},
    "settings_json": {"settings.json": "{}"},
    "bin_dir": {"bin/tool": "x"},
    "shell_line": {"SKILL.md": "---\nname: s\n---\nRun !`ls`\n"},
    "allowed_tools": {"SKILL.md": "---\nname: s\nallowed-tools: Bash(*)\n---\nx\n"},
    "case_varied_plugin_manifest": {".Claude-Plugin/plugin.json": "{}"},
    "plain_py_0644": {"helper.py": "print('hi')\n"},
    "plain_sh_0644_nested": {"tools/run.sh": "echo hi\n"},
    "upper_case_extension": {"tools/RUN.PY": "print('hi')\n"},
    "shebang_no_extension": {"tools/run": "#!/usr/bin/env python3\nprint('hi')\n"},
    "upper_case_hooks": {"Hooks/HOOKS.JSON": "{}"},
    "upper_case_settings": {"SETTINGS.JSON": "{}"},
    "nested_claude_plugin": {"sub/dir/.claude-plugin/plugin.json": "{}"},
    "allowed_python_plus_helper": {
        "SKILL.md": "---\nname: s\nallowed-tools: Bash(python3:*)\n---\nsee reference.md\n",
        "helper.py": "print('hi')\n",
        "reference.md": "Run python3 helper.py\n",
    },
}


@pytest.mark.parametrize("case", sorted(SKILL_CODE_CASES))
def test_skill_folder_with_code_takes_the_consent_path(tmp_path, case):
    (tmp_path / "SKILL.md").write_text("---\nname: s\n---\nhi\n")
    for rel, content in SKILL_CODE_CASES[case].items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert staged_plugin_declares_code(kinds.KIND_SKILL, tmp_path) is True


def test_plain_skill_folder_needs_no_code_consent(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nhi\n")
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "a.md").write_text("notes\n")
    assert staged_plugin_declares_code(kinds.KIND_SKILL, tmp_path) is False


@pytest.mark.parametrize("files", [{"lib/server.py": "print(1)\n"}, {"lib/tool": "#!/bin/sh\necho hi\n"}])
def test_plugin_with_a_plain_script_file_takes_the_consent_path(tmp_path, files):
    """A plugin's 0644 script file or shebang file is code at install and update (#2557)."""
    folder = _plugin(tmp_path, files=files)
    assert staged_plugin_declares_code(kinds.KIND_PLUGIN, folder) is True


def test_text_files_without_a_shebang_stay_text(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: s\n---\nrun helper.py\n")
    (tmp_path / "notes.txt").write_text("# not a shebang\n")
    (tmp_path / "data.json").write_text("{}\n")
    assert staged_plugin_declares_code(kinds.KIND_SKILL, tmp_path) is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a 0000 file")
def test_an_unreadable_file_counts_as_code(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: s\n---\nhi\n")
    blob = tmp_path / "data.bin"
    blob.write_bytes(b"opaque")
    blob.chmod(0)
    try:
        assert staged_plugin_declares_code(kinds.KIND_SKILL, tmp_path) is True
    finally:
        blob.chmod(0o644)
