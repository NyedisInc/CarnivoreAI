
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "signing" / "sign-dev-electron.sh"

CODESIGN = """#!/bin/bash
# stub: STATE=signed answers a valid MDH8UQ6H46 signature, anything else an ad hoc one;
# wrongteam / wrongid verify fine but name another team / identifier
case " $* " in
  *" --verify "*) [ "$STATE" != adhoc ]; exit $? ;;
  *" -dv "*) if [ "$STATE" = wrongteam ]; then printf 'Identifier=com.github.Electron\\nTeamIdentifier=ARD6KN4BX4\\n' >&2;
             elif [ "$STATE" = wrongid ]; then printf 'Identifier=Electron\\nTeamIdentifier=MDH8UQ6H46\\n' >&2;
             elif [ "$STATE" = signed ]; then printf 'Identifier=com.github.Electron\\nTeamIdentifier=MDH8UQ6H46\\n' >&2;
             else printf 'Identifier=Electron\\nTeamIdentifier=not set\\n' >&2; fi ;;
esac
exit 0
"""
LOGGER = '#!/bin/bash\necho "$0 $*" >> "$STUB_LOG"\nexit 1\n'


def run(tmp_path: Path, state: str, *args: str, keychain: bool = False):
    bin_dir, home = tmp_path / "bin", tmp_path / "home"
    (home / "Library" / "Keychains").mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("codesign", CODESIGN), ("aws", LOGGER), ("security", LOGGER)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod((bin_dir / name).stat().st_mode | stat.S_IXUSR)
    if keychain:
        (home / "Library" / "Keychains" / "carnivore-signing.keychain-db").write_text("x")
    app = tmp_path / "Electron.app"
    app.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home),
           "STATE": state, "STUB_LOG": str(log)}
    done = subprocess.run([str(SCRIPT), "--app", str(app), *args], env=env,
                          capture_output=True, text=True, timeout=60)
    return done, (log.read_text() if log.exists() else "")


def test_signed_with_the_right_team_is_skipped(tmp_path):
    done, calls = run(tmp_path, "signed", keychain=True)
    assert done.returncode == 0 and "already signed" in done.stdout
    assert calls == ""


def test_ad_hoc_needs_signing(tmp_path):
    done, _ = run(tmp_path, "adhoc", "--check")
    assert done.returncode == 0 and done.stdout.strip() == "needs-signing"


def test_valid_signature_of_another_team_or_identifier_needs_signing(tmp_path):
    for state in ("wrongteam", "wrongid"):
        done, _ = run(tmp_path / state, state, "--check")
        assert done.returncode == 0 and done.stdout.strip() == "needs-signing", state


def test_interrupt_between_the_swap_moves_restores_the_original(tmp_path):
    text = SCRIPT.read_text()
    assert 'if [[ -n "$old" && -d "$old" && ! -e "$app" ]]; then mv "$old" "$app"; fi' in text
    app, old = tmp_path / "Electron.app", tmp_path / "Electron.app.old.1"
    old.mkdir()
    (old / "marker").write_text("x")
    snippet = f'app="{app}"; old="{old}"; ' + 'if [[ -n "$old" && -d "$old" && ! -e "$app" ]]; then mv "$old" "$app"; fi'
    subprocess.run(["bash", "-c", snippet], check=True)
    assert (app / "marker").exists() and not old.exists()


def test_no_keychain_warns_and_leaves_the_app(tmp_path):
    done, calls = run(tmp_path, "adhoc")
    assert done.returncode == 3 and "WARNING" in done.stderr and calls == ""


def test_no_aws_credentials_warns_and_never_opens_the_keychain(tmp_path):
    done, calls = run(tmp_path, "adhoc", keychain=True)
    assert done.returncode == 3 and "WARNING" in done.stderr
    assert "aws" in calls and "security" not in calls
    assert not (tmp_path / "home" / "Library" / "Keychains" / "carnivore-signing.pass.lock").exists()
