
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.plugins.cli import main as cli_main
from src.plugins.cli import templates
from src.plugins.runtime import sandbox
from src.plugins.sdk.manifest_v2 import load_manifest_v2


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


@pytest.mark.parametrize("template", templates.TEMPLATES)
def test_all_7_v2_templates_scaffold_check_and_test(
    tmp_path: Path,
    template: str,
    capsys: pytest.CaptureFixture,
) -> None:
    if template in ("python", "widget", "channel", "typescript", "bash") and not DARWIN_SANDBOX:
        pytest.skip("sandbox smoke probe requires macOS sandbox-exec")

    name = f"demo{template.replace('-', '')}"[:20]
    dest = tmp_path / name
    assert cli_main(["new", name, "--template", template, "--dir", str(dest)]) == 0
    assert (dest / "carnivore.toml").is_file()
    assert (dest / "LICENSE.md").is_file()
    if template == "bash":
        assert os.access(dest / "run.sh", os.X_OK)

    manifest = load_manifest_v2(dest, allow_tier_override=True)
    assert manifest.id == name
    assert manifest.license == "MIT"

    assert cli_main(["check", str(dest)]) == 0, capsys.readouterr().out
    assert cli_main(["test", str(dest)]) == 0, capsys.readouterr().out


def test_cli_new_refuses_bad_and_reserved_names(tmp_path: Path) -> None:
    from src.plugins.cli import checker
    from src.plugins.sdk import cplug_validate

    for reserved in ("flow", "huddle", "taskmanager", "sessionchat", "nudge", "publicboard"):
        assert cli_main(["new", reserved, "--dir", str(tmp_path / f"res-{reserved}")]) == 2
        plug = tmp_path / f"chk-{reserved}"
        plug.mkdir()
        (plug / "carnivore.toml").write_text(
            f'schema = 2\nid = "{reserved}"\nname = "X"\nversion = "1.0.0"\nkind = "plugin"\ndescription = "d"\nauthor = "a"\n',
            encoding="utf-8",
        )
        rep = checker.check_folder(plug)
        assert not rep.ok, reserved
        assert any("reserved" in err for err in rep.errors), (reserved, rep.errors)

    for rid in cplug_validate.RESERVED_IDS:
        assert templates.name_problem(rid)

    assert cli_main(["new", "Bad-Id", "--dir", str(tmp_path / "b")]) == 2


def test_cli_check_and_test_fail_on_broken_plugin(tmp_path: Path) -> None:
    dest = tmp_path / "brokenone"
    assert cli_main(["new", "brokenone", "--template", "python", "--dir", str(dest)]) == 0

    (dest / "tests" / "test_brokenone.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    assert cli_main(["test", str(dest), "--unit-only"]) == 1

    (dest / "carnivore.toml").write_text("schema = 2\nid = 'brokenone'\n", encoding="utf-8")
    assert cli_main(["check", str(dest)]) == 1


def test_cli_channel_test_json_stdout_is_clean_single_json(tmp_path: Path) -> None:
    if not DARWIN_SANDBOX:
        pytest.skip("sandbox smoke probe requires macOS sandbox-exec")
    dest = tmp_path / "probechan"
    assert cli_main(["new", "probechan", "--template", "channel", "--dir", str(dest)]) == 0

    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [sys.executable, "-m", "src.tui", "plugin", "test", str(dest), "--json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["ok"] is True


def test_bash_template_matches_method_key_not_param_substrings(tmp_path: Path) -> None:
    dest = tmp_path / "bashmethod"
    assert cli_main(["new", "bashmethod", "--template", "bash", "--dir", str(dest)]) == 0
    frames = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ui.render", "params": {"surface": "widget", "note": "initialize"}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {"reason": "shutdown"}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}),
    ]) + "\n"
    proc = subprocess.run(
        [str(dest / "run.sh")],
        cwd=str(dest),
        input=frames,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert "document" in replies[0]["result"]
    assert replies[1]["result"] == {"ok": True}
    assert replies[2]["result"] == {"ok": True}
