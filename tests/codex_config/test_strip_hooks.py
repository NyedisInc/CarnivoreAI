
import json
import tomllib

from src.core.codex_config.strip_hooks import strip_codex_managed_hooks

MANAGED = '(cat | curl -sS -m 2 -X POST "$CLOUDECODE_HOOK_URL") > /dev/null 2>&1 ; : # cloudecode-managed'


def _entry(cmd: str) -> dict:
    return {"hooks": [{"type": "command", "command": cmd}]}


def test_managed_entries_and_trust_go_user_entries_stay(tmp_path) -> None:
    hooks = tmp_path / "hooks.json"
    doc = {"hooks": {
        "PreToolUse": [_entry("user-a"), _entry(MANAGED), _entry("user-b")],
        "SessionEnd": [_entry(MANAGED)],
        "Stop": [_entry("user-c")],
    }}
    hooks.write_text(json.dumps(doc, indent=2) + "\n")
    key = f'{hooks}'
    cfg = tmp_path / "config.toml"
    head = '# my comment\nmodel = "x"   # keep\n\n[hooks.state]\n\n'
    tail = '[other]\nk = 1\n'
    cfg.write_text(
        head
        + f'[hooks.state."{key}:pre_tool_use:0:0"]\ntrusted_hash = "sha256:a"\n\n'
        + f'[hooks.state."{key}:pre_tool_use:1:0"]\ntrusted_hash = "sha256:m"\n\n'
        + f'[hooks.state."{key}:pre_tool_use:2:0"]\ntrusted_hash = "sha256:b"\n\n'
        + f'[hooks.state."{key}:session_end:0:0"]\ntrusted_hash = "sha256:m2"\n\n'
        + f'[hooks.state."/elsewhere/hooks.json:pre_tool_use:1:0"]\ntrusted_hash = "sha256:z"\n\n'
        + tail)

    assert strip_codex_managed_hooks(tmp_path) is True

    out = json.loads(hooks.read_text())
    assert out == {"hooks": {"PreToolUse": [_entry("user-a"), _entry("user-b")], "Stop": [_entry("user-c")]}}
    text = cfg.read_text()
    assert "cloudecode-managed" not in hooks.read_text()
    assert text == (
        head
        + f'[hooks.state."{key}:pre_tool_use:0:0"]\ntrusted_hash = "sha256:a"\n\n'
        + f'[hooks.state."{key}:pre_tool_use:1:0"]\ntrusted_hash = "sha256:b"\n\n'
        + f'[hooks.state."/elsewhere/hooks.json:pre_tool_use:1:0"]\ntrusted_hash = "sha256:z"\n\n'
        + tail)
    tomllib.loads(text)
    assert len(list(tmp_path.glob("hooks.json.cloudecode-bak-*"))) == 1
    assert len(list(tmp_path.glob("config.toml.cloudecode-bak-*"))) == 1

    before = hooks.read_bytes()
    assert strip_codex_managed_hooks(tmp_path) is True
    assert hooks.read_bytes() == before
    assert len(list(tmp_path.glob("hooks.json.cloudecode-bak-*"))) == 1


def test_missing_and_unparseable_files_are_skipped(tmp_path) -> None:
    assert strip_codex_managed_hooks(tmp_path) is True
    (tmp_path / "hooks.json").write_text("{not json")
    assert strip_codex_managed_hooks(tmp_path) is False
    assert (tmp_path / "hooks.json").read_text() == "{not json"
