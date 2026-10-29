
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RIG = REPO / "macOS" / "scripts" / "vm-rig"
MAC_SCRIPTS = REPO / "macOS" / "scripts"
GATE = REPO / "scripts" / "release" / "spare_key_gate.py"

FORBIDDEN = re.compile(
    r"(^|[;&|(\s])gh\s|aws\s+s3|\bcurl\s+[^|]*-X\s*(POST|PUT)|publish-update-assets|NyedisInc"
    r"|MDH8UQ6H46|--publish\s+always|\bupload\b|\bgh release\b"
)
HOST_CURL = re.compile(r"^\s*curl\s", re.M)


def publish_findings(scripts: list[Path]) -> list[str]:
    if not scripts:
        raise AssertionError("the publish scan looked at nothing")
    found = []
    for path in scripts:
        code = "\n".join(
            line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        for hit in FORBIDDEN.finditer(code):
            found.append(f"{path.name}: {hit.group(0).strip()}")
        if HOST_CURL.search(code):
            found.append(f"{path.name}: curl")
    return found


def test_the_scan_flags_a_publish_fixture_and_refuses_an_empty_population(tmp_path):
    bad_gh = tmp_path / "bad_gh.sh"
    bad_gh.write_text("#!/bin/bash\ngh release upload v1 app.dmg\n")
    bad_team = tmp_path / "bad_team.sh"
    bad_team.write_text("#!/bin/bash\nTEAM=MDH8UQ6H46\n")
    good = tmp_path / "good.sh"
    good.write_text("#!/bin/bash\n# gh release upload is forbidden here\necho through the night\n")
    assert publish_findings([bad_gh])
    assert publish_findings([bad_team])
    assert publish_findings([good]) == []
    with pytest.raises(AssertionError):
        publish_findings([])


def test_the_real_rig_scripts_contain_no_publish_path():
    scripts = sorted(RIG.glob("*.sh"))
    assert len(scripts) >= 7
    assert publish_findings(scripts) == []




@pytest.fixture
def rig(tmp_path):
    tree = tmp_path / "tree"
    dest = tree / "macOS" / "scripts" / "vm-rig"
    dest.mkdir(parents=True)
    for script in RIG.glob("*.sh"):
        shutil.copy2(script, dest / script.name)
    log = tmp_path / "calls.log"
    fake_build = tree / "macOS" / "scripts" / "release-build.sh"
    fake_build.write_text(
        '#!/bin/bash\ncd "$(dirname "$0")/.."\n'
        f'echo "release-build purpose=${{CARNIVORE_BUILD_PURPOSE:-}} args=$*" >> "{log}"\n'
        'mkdir -p dist-vmtest/mac-universal/Carnivore.app\n'
    )
    fake_build.chmod(0o755)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    fakes = {
        "tart": f'echo "tart $*" >> "{log}"\n[ "$1" = ip ] && echo 192.0.2.7\nexit 0',
        "sshpass": 'shift\nexec "$@"',
        "ssh": (
            f'cmd="${{!#}}"\necho "ssh $cmd" >> "{log}"\n[ -t 0 ] || cat > /dev/null\n'
            'if [ -n "$FAKE_FAIL" ] && [[ "$cmd" == *"$FAKE_FAIL"* ]]; then echo boom; exit 1; fi\n'
            'case "$cmd" in\n'
            '  *"grep -c com.apple.quarantine"*) echo "${FAKE_QUARANTINE:-0}" ;;\n'
            '  *"codesign -dv"*) echo "Identifier=ai.carnivore.menubar"; echo "TeamIdentifier=${FAKE_TEAM:-ARD6KN4BX4}" ;;\n'
            '  *) echo "ok $cmd" ;;\nesac'
        ),
        "nc": "exit 0",
        "codesign": 'echo "TeamIdentifier=${FAKE_TEAM:-ARD6KN4BX4}" >&2',
        "xcrun": f'echo "xcrun $*" >> "{log}"\nexit "${{FAKE_STAPLE:-0}}"',
    }
    for name, body in fakes.items():
        stub = stubs / name
        stub.write_text(f"#!/bin/bash\n{body}\n")
        stub.chmod(0o755)
    return tree, stubs, log, tmp_path


def run(rig, script: str, *args: str, **env) -> tuple[subprocess.CompletedProcess, str]:
    tree, stubs, log, tmp = rig
    full = {"PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp), **env}
    done = subprocess.run(
        ["bash", str(tree / "macOS/scripts/vm-rig" / script), *args],
        capture_output=True, text=True, env=full, timeout=60, check=False, cwd=tmp,
    )
    return done, (log.read_text() if log.exists() else "")


def test_build_test_app_sets_the_purpose_and_never_publishes(rig):
    done, calls = run(rig, "build-test-app.sh")
    assert done.returncode == 0, done.stderr
    assert "purpose=vm-test args=-c.directories.output=dist-vmtest --publish never" in calls
    assert done.stdout.strip().endswith("dist-vmtest/mac-universal/Carnivore.app")
    assert "xcrun stapler validate" in calls


def test_build_test_app_fails_on_the_wrong_team_or_a_missing_ticket(rig):
    wrong_team, _ = run(rig, "build-test-app.sh", FAKE_TEAM="MDH8UQ6H46")
    assert wrong_team.returncode != 0 and "wrong signing team" in wrong_team.stderr
    unstapled, _ = run(rig, "build-test-app.sh", FAKE_STAPLE="1")
    assert unstapled.returncode != 0 and "no notarization ticket" in unstapled.stderr


def test_reset_refuses_a_golden_guest_and_deletes_before_it_clones(rig):
    for golden in ("carnivore-macos14", "carnivore-macos26"):
        done, calls = run(rig, "vm-reset.sh", golden)
        assert done.returncode != 0 and "golden" in done.stderr
        assert "tart delete" not in calls and "tart clone" not in calls
    odd, calls = run(rig, "vm-reset.sh", "some-other-vm")
    assert odd.returncode != 0 and "tart clone" not in calls
    done, calls = run(rig, "vm-reset.sh", "carnivore-macos26-run")
    assert done.returncode == 0, done.stderr
    assert calls.index("tart delete carnivore-macos26-run") < calls.index(
        "tart clone carnivore-macos26 carnivore-macos26-run"
    )


def test_reset_and_start_accept_a_named_clone_of_a_golden_guest(rig):
    done, calls = run(rig, "vm-reset.sh", "carnivore-macos14-r2proof")
    assert done.returncode == 0, done.stderr
    assert "tart clone carnivore-macos14 carnivore-macos14-r2proof" in calls
    started, calls = run(rig, "vm-start.sh", "carnivore-macos26-r2proof", CARNIVORE_VM_LOG_DIR=str(rig[3]))
    assert started.returncode == 0, started.stderr
    assert "tart run --no-graphics carnivore-macos26-r2proof" in calls
    before = len(calls)
    stranger, calls = run(rig, "vm-reset.sh", "carnivore-macos99-run")
    assert stranger.returncode != 0 and len(calls) == before


def test_install_fails_on_a_quarantine_attribute_and_passes_without_one(rig):
    tmp = rig[3]
    app = tmp / "Carnivore.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "marker").write_text("x")
    quarantined, _ = run(rig, "vm-install.sh", "carnivore-macos14-run", str(app), FAKE_QUARANTINE="2")
    assert quarantined.returncode != 0 and "quarantine" in quarantined.stderr
    wrong, _ = run(rig, "vm-install.sh", "carnivore-macos14-run", str(app), FAKE_TEAM="MDH8UQ6H46")
    assert wrong.returncode != 0 and "reads back team" in wrong.stderr
    done, calls = run(rig, "vm-install.sh", "carnivore-macos14-run", str(app))
    assert done.returncode == 0, done.stderr
    assert "TeamIdentifier=ARD6KN4BX4" in done.stdout
    assert "tar -C /Applications -xf -" in calls


def test_start_boots_headless_a_run_clone_only_and_stop_stops_it(rig):
    env = {"CARNIVORE_VM_LOG_DIR": str(rig[3])}
    golden, calls = run(rig, "vm-start.sh", "carnivore-macos14", **env)
    assert golden.returncode != 0 and "tart run" not in calls
    done, calls = run(rig, "vm-start.sh", "carnivore-macos14-run", **env)
    assert done.returncode == 0, done.stderr
    assert "tart run --no-graphics carnivore-macos14-run" in calls
    stopped, calls = run(rig, "vm-stop.sh", "carnivore-macos14-run")
    assert stopped.returncode == 0 and "tart stop carnivore-macos14-run" in calls


FIELDS = [
    "os_version", "app_version", "codesign", "spctl", "gatekeeper", "quarantine", "launchctl", "btm",
    "tmux_sessions", "version_route", "dialog_audit", "notification_posts",
]


def test_readout_writes_every_field_and_marks_a_failed_one_not_available(rig):
    out = rig[3] / "readout.md"
    done, _ = run(rig, "vm-readout.sh", "carnivore-macos14-run", str(out))
    assert done.returncode == 0, done.stderr
    text = out.read_text()
    assert re.findall(r"^## field: (\w+)$", text, re.M) == FIELDS
    assert "not available" not in text
    out2 = rig[3] / "readout2.md"
    done, _ = run(rig, "vm-readout.sh", "carnivore-macos14-run", str(out2), FAKE_FAIL="sfltool")
    assert done.returncode == 0
    assert re.search(r"## field: btm\nnot available: exit 1: boom", out2.read_text())
    assert len(re.findall(r"^## field: ", out2.read_text(), re.M)) == len(FIELDS)
    nofile, _ = run(rig, "vm-readout.sh", "carnivore-macos14-run")
    assert nofile.returncode != 0




@pytest.fixture
def build_tree(tmp_path):
    tree = tmp_path / "tree"
    for src, rel in (
        (MAC_SCRIPTS / "release-build.sh", "macOS/scripts/release-build.sh"),
        (MAC_SCRIPTS / "signing-keychain-session.sh", "macOS/scripts/signing-keychain-session.sh"),
        (MAC_SCRIPTS / "pip-audit-lock.sh", "macOS/scripts/pip-audit-lock.sh"),
        (GATE, "scripts/release/spare_key_gate.py"),
    ):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, tree / rel)
    root = tree / "src/core/catalog/trust_root.py"
    root.parent.mkdir(parents=True)
    root.write_text(
        'SPARE_INDEX_KEY_PLACEHOLDER: str = "UNSET"\nSPARE_INDEX_PUBLIC_KEY: str = SPARE_INDEX_KEY_PLACEHOLDER\n'
    )
    (tree / "macOS/package.json").write_text(json.dumps({"name": "x", "version": "1", "requireSpareIndexKey": True}))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    for tool, status in (("aws", 1), ("security", 1), ("node", 1), ("npm", 0)):
        stub = stubs / tool
        policy = 'case "$1" in scripts/electron-policy.js|scripts/electron-fuses-check.js) exit 0;; esac\n' if tool == "node" else ""
        stub.write_text(f'#!/bin/sh\n{policy}echo "{tool} $*" >> "{log}"\nexit {status}\n')
        stub.chmod(0o755)
    home = tmp_path / "home"
    (home / "Library" / "Keychains").mkdir(parents=True)
    (home / "Library" / "Keychains" / "carnivore-signing.keychain-db").write_bytes(b"")
    return tree, stubs, home, log


def _build(build_tree, purpose: str) -> tuple[subprocess.CompletedProcess, str]:
    tree, stubs, home, log = build_tree
    env = {"PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "HOME": str(home), "TMPDIR": str(home)}
    if purpose:
        env["CARNIVORE_BUILD_PURPOSE"] = purpose
    done = subprocess.run(
        ["bash", str(tree / "macOS/scripts/release-build.sh")],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    return done, (log.read_text() if log.exists() else "")


def test_a_vm_test_build_is_not_a_release_but_a_release_purpose_still_is(build_tree):
    release, release_calls = _build(build_tree, "")
    assert "spare_key_gate: REFUSED" in release.stderr and release_calls == ""
    proof, _ = _build(build_tree, "update-proof")
    assert "REFUSED" not in proof.stderr
    vm_test, calls = _build(build_tree, "vm-test")
    assert "spare_key_gate: warning" in vm_test.stderr
    assert "REFUSED" not in vm_test.stderr
    assert calls != ""


def test_a_test_build_stamps_its_purpose_into_the_bundle_and_an_unknown_purpose_dies(build_tree):
    _, _, home, _ = build_tree
    (home / "Library" / "Keychains" / "carnivore-signing.keychain-db").unlink()
    for purpose in ("vm-test", "update-proof"):
        done, calls = _build(build_tree, purpose)
        assert done.returncode == 0, done.stderr
        assert f"-c.mac.extendInfo.CarnivoreBuildPurpose={purpose}" in calls
    done, calls = _build(build_tree, "")
    assert done.returncode == 0, done.stderr
    last = calls.strip().splitlines()[-1]
    assert "CarnivoreBuildPurpose" not in last and "package" in last
    done, _ = _build(build_tree, "release-candidate")
    assert done.returncode == 1 and "unknown CARNIVORE_BUILD_PURPOSE" in done.stderr
