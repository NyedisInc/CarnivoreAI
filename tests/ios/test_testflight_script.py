
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("TESTFLIGHT_SCRIPT", ROOT / "scripts" / "ios" / "testflight.sh"))
MARKER = "P8-MARKER-9f3a1c77d2"
KEY_ID = "ABCDE12345"
ISSUER = "11111111-2222-3333-4444-555555555555"

FAKE_AWS = f"""#!/bin/bash
echo "$@" >> "$FAKE_LOG/aws.argv"
if [ -n "${{FAKE_NO_SECRET:-}}" ]; then
  echo "An error occurred (ResourceNotFoundException) when calling the GetSecretValue operation" >&2
  exit 254
fi
printf '{{"key_id": "{KEY_ID}", "issuer_id": "{ISSUER}", "p8": "-----BEGIN PRIVATE KEY-----\\\\n{MARKER}\\\\n-----END PRIVATE KEY-----"}}'
"""

FAKE_XCODEGEN = """#!/bin/bash
echo "$@" >> "$FAKE_LOG/xcodegen.argv"
"""

FAKE_XCODEBUILD = """#!/bin/bash
echo "$@" >> "$FAKE_LOG/xcodebuild.argv"
prev=""
for a in "$@"; do
  if [ "$prev" = "-authenticationKeyPath" ]; then
    echo "keymode=$(stat -f %Lp "$a" 2>/dev/null || stat -c %a "$a") dirmode=$(stat -f %Lp "$(dirname "$a")" 2>/dev/null || stat -c %a "$(dirname "$a")")" >> "$FAKE_LOG/modes"
    grep -q "$FAKE_MARKER" "$a" && echo keyhasmarker >> "$FAKE_LOG/modes"
  fi
  if [ "$prev" = "-exportOptionsPlist" ]; then cp "$a" "$FAKE_LOG/ExportOptions.plist"; fi
  prev="$a"
done
[ -n "${FAKE_XCODEBUILD_OUT:-}" ] && { cat "$FAKE_XCODEBUILD_OUT"; exit 65; }
[ -n "${FAKE_XCODEBUILD_FAIL:-}" ] && { echo "boom"; exit 1; }
exit 0
"""


def _run(tmp_path: Path, *args: str, **env: str) -> tuple:
    bin_dir, log, tmp = tmp_path / "bin", tmp_path / "log", tmp_path / "tmp"
    for d in (bin_dir, log, tmp):
        d.mkdir(exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("xcodegen", FAKE_XCODEGEN), ("xcodebuild", FAKE_XCODEBUILD)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    full = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(log), "FAKE_MARKER": MARKER, "TMPDIR": str(tmp), **env}
    proc = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=full, timeout=60)
    return proc, log, tmp


def _everything(proc: subprocess.CompletedProcess, log: Path) -> str:
    return proc.stdout + proc.stderr + "".join(p.read_text() for p in log.glob("*.argv"))


def test_success_hides_p8_cleans_up_and_exports_with_upload(tmp_path: Path) -> None:
    proc, log, tmp = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert MARKER not in _everything(proc, log)
    assert "keymode=600 dirmode=700" in (log / "modes").read_text()
    assert "keyhasmarker" in (log / "modes").read_text()
    assert list(tmp.iterdir()) == []
    assert "<key>destination</key><string>upload</string>" in (log / "ExportOptions.plist").read_text()
    assert "uploaded to App Store Connect: version 0.1.0 build " in proc.stdout
    argv = (log / "xcodebuild.argv").read_text()
    assert f"-authenticationKeyID {KEY_ID}" in argv and "-allowProvisioningUpdates" in argv


def test_forced_failure_still_cleans_up_and_hides_p8(tmp_path: Path) -> None:
    proc, log, tmp = _run(tmp_path, FAKE_XCODEBUILD_FAIL="1")
    assert proc.returncode == 1
    assert MARKER not in _everything(proc, log)
    assert list(tmp.iterdir()) == []


def test_missing_secret_exits_3_with_named_line(tmp_path: Path) -> None:
    proc, log, tmp = _run(tmp_path, FAKE_NO_SECRET="1")
    assert proc.returncode == 3
    assert "app store connect key not configured" in proc.stderr
    assert not (log / "xcodebuild.argv").exists()
    assert list(tmp.iterdir()) == []


def test_dry_run_reads_no_secret_and_builds_unsigned(tmp_path: Path) -> None:
    proc, log, tmp = _run(tmp_path, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert not (log / "aws.argv").exists()
    assert "CODE_SIGNING_ALLOWED=NO" in (log / "xcodebuild.argv").read_text()
    assert list(tmp.iterdir()) == []


AUTH_LINE = "error: Authentication failed: Make sure a bearer token was provided, it is properly configured and signed, and it has not expired."


@pytest.mark.parametrize("lines", [
    [AUTH_LINE, "error: No profiles for 'ai.carnivore.ios' were found"],
    ["error: No profiles for 'ai.carnivore.ios.notify' were found"],
])
def test_no_profiles_names_the_app_group_click(tmp_path: Path, lines: list) -> None:
    out = tmp_path / "xcodebuild.out"
    out.write_text("\n".join(lines) + "\n")
    proc, _log, _tmp = _run(tmp_path, "--dry-run", FAKE_XCODEBUILD_OUT=str(out))
    assert proc.returncode == 4, proc.stderr
    assert "group.ai.carnivore" in proc.stderr
    assert "ai.carnivore.ios" in proc.stderr and "ai.carnivore.ios.notify" in proc.stderr
    assert "role is Admin" not in proc.stderr


def test_role_signature_keeps_the_key_role_message(tmp_path: Path) -> None:
    out = tmp_path / "xcodebuild.out"
    out.write_text("error: Your account doesn't have permission to do this\n")
    proc, _log, _tmp = _run(tmp_path, "--dry-run", FAKE_XCODEBUILD_OUT=str(out))
    assert proc.returncode == 4, proc.stderr
    assert "role is Admin" in proc.stderr
