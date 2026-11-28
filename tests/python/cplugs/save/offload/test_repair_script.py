
from __future__ import annotations

import hashlib
import json
import lzma
import os
import stat
import subprocess
from pathlib import Path
from typing import Dict

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "vault" / "repair-chunks-from-restic.sh"
RAW = b"a chunk of conversation bytes\n" * 20
NAME = hashlib.sha256(RAW).hexdigest()


def stub(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def rig(tmp_path: Path) -> Dict[str, Path]:
    vault, tools, snapshot = tmp_path / "vault", tmp_path / "bin", tmp_path / "snapshot"
    (vault / "blobs" / NAME[:2]).mkdir(parents=True)
    (vault / "blobs" / NAME[:2] / f"{NAME}.xz").write_bytes(b"damaged")
    tools.mkdir()
    (snapshot / "blobs" / NAME[:2]).mkdir(parents=True)
    (snapshot / "blobs" / NAME[:2] / f"{NAME}.xz").write_bytes(lzma.compress(RAW))
    find = json.dumps([{"snapshot": "abcdef123456", "matches": [{"path": f"/vault/blobs/{NAME[:2]}/{NAME}.xz"}]}])
    stub(tools, "op", 'echo "value-of-$2"')
    stub(tools, "restic", f'''
case "$1" in
  find) echo '{find}' ;;
  restore) target=""; while [ $# -gt 0 ]; do [ "$1" = "--target" ] && target="$2"; shift; done
           mkdir -p "$target/vault/blobs/{NAME[:2]}"; cp "{snapshot}/blobs/{NAME[:2]}/{NAME}.xz" "$target/vault/blobs/{NAME[:2]}/" ;;
esac''')
    return {"vault": vault, "tools": tools}


def run(rig: Dict[str, Path], tmp_path: Path, *args: str, env_extra: Dict[str, str] | None = None) -> subprocess.CompletedProcess:
    home = tmp_path / "home"
    (home / ".Trash").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trash").mkdir(exist_ok=True)
    env = {"PATH": f"{rig['tools']}:{os.environ['PATH']}", "HOME": str(home), "TMPDIR": str(tmp_path), "RESTIC_REPO_REF": "op://x/y/repo", "RESTIC_PASSWORD_REF": "op://x/y/pw",
           "REPAIR_TRASH_DIR": str(tmp_path / "trash"), **(env_extra or {})}
    return subprocess.run(["bash", str(SCRIPT), "--vault", str(rig["vault"]), *args], env=env, capture_output=True, text=True, timeout=60)


def test_a_damaged_chunk_is_set_aside_and_replaced_by_the_proven_restic_copy(rig, tmp_path) -> None:
    out = run(rig, tmp_path, "--blobs", NAME)
    assert out.returncode == 0, out.stdout + out.stderr
    fixed = rig["vault"] / "blobs" / NAME[:2] / f"{NAME}.xz"
    assert hashlib.sha256(lzma.decompress(fixed.read_bytes())).hexdigest() == NAME
    assert [p.read_bytes() for p in (rig["vault"] / "blobs-quarantine").rglob("*.xz")] == [b"damaged"]


def test_a_good_chunk_is_left_alone_and_a_dry_run_changes_nothing(rig, tmp_path) -> None:
    target = rig["vault"] / "blobs" / NAME[:2] / f"{NAME}.xz"
    out = run(rig, tmp_path, "--dry-run", "--blobs", NAME)
    assert out.returncode == 0 and target.read_bytes() == b"damaged" and not (rig["vault"] / "blobs-quarantine").exists()
    target.write_bytes(lzma.compress(RAW))
    before = target.stat().st_mtime_ns
    out = run(rig, tmp_path, "--blobs", NAME)
    assert out.returncode == 0 and "already good" in out.stdout and target.stat().st_mtime_ns == before


def test_names_come_from_the_health_record_and_a_chunk_restic_lacks_fails_the_run(rig, tmp_path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    other = "f" * 64
    (state / "vault-health.json").write_text(json.dumps({"offload_alerts": {"scrub": {"blobs": [NAME]}, "purge": {"blobs": [other]}}}))
    stub(rig["tools"], "restic", f'''case "$1" in find) case "$*" in *{other}*) echo '[]' ;; *) echo '{json.dumps([{"snapshot": "abcdef123456", "matches": [{"path": "/x"}]}])}' ;; esac ;; restore) exit 1 ;; esac''')
    out = run(rig, tmp_path, "--from-health", str(state))
    assert out.returncode == 1 and f"NOT IN RESTIC: {other}" in out.stdout


def test_the_script_holds_no_credentials_and_refuses_without_references(rig, tmp_path) -> None:
    text = SCRIPT.read_text()
    assert "op://<vault>" in text and "RESTIC_PASSWORD=" in text and "sftp:" not in text.replace("sftp:host", "")
    out = run(rig, tmp_path, "--blobs", NAME, env_extra={"RESTIC_REPO_REF": ""})
    assert out.returncode == 2


def test_a_zst_chunk_is_never_replaced_when_it_cannot_be_checked(rig, tmp_path) -> None:
    import shutil

    system_path = "/usr/bin:/bin"
    if shutil.which("zstd", path=system_path) or not shutil.which("python3", path=system_path):
        pytest.skip("needs a system PATH with python3 and without zstd")
    folder = rig["vault"] / "blobs" / NAME[:2]
    (folder / f"{NAME}.xz").unlink()
    (folder / f"{NAME}.zst").write_bytes(b"maybe good, cannot tell")
    out = run(rig, tmp_path, "--blobs", NAME, env_extra={"PATH": f"{rig['tools']}:{system_path}"})
    assert out.returncode == 1, out.stdout + out.stderr
    assert (folder / f"{NAME}.zst").read_bytes() == b"maybe good, cannot tell" and not (rig["vault"] / "blobs-quarantine").exists()
    (folder / f"{NAME}.zst").unlink()
    snapshot = tmp_path / "snapshot" / "blobs" / NAME[:2]
    (snapshot / f"{NAME}.zst").write_bytes(b"unprovable")
    find = json.dumps([{"snapshot": "abcdef123456", "matches": [{"path": f"/vault/blobs/{NAME[:2]}/{NAME}.zst"}]}])
    stub(rig["tools"], "restic", f'''case "$1" in find) echo '{find}' ;; restore) target=""; while [ $# -gt 0 ]; do [ "$1" = "--target" ] && target="$2"; shift; done
           mkdir -p "$target/vault/blobs/{NAME[:2]}"; cp "{snapshot}/{NAME}.zst" "$target/vault/blobs/{NAME[:2]}/" ;; esac''')
    out = run(rig, tmp_path, "--blobs", NAME, env_extra={"PATH": f"{rig['tools']}:{system_path}"})
    assert out.returncode == 1 and not list(folder.iterdir()), out.stdout


def test_the_temp_folder_goes_to_the_drive_trash_never_the_home_trash(rig, tmp_path) -> None:
    out = run(rig, tmp_path, "--blobs", NAME)
    assert out.returncode == 0, out.stdout + out.stderr
    assert [p.name.startswith("repair-chunks.") for p in (tmp_path / "trash").iterdir()] == [True]
    assert list((tmp_path / "home" / ".Trash").iterdir()) == []
    out = run(rig, tmp_path, "--blobs", NAME, env_extra={"REPAIR_TRASH_DIR": str(tmp_path / "no-such-drive")})
    assert out.returncode == 0 and "temp folder left at" in out.stdout
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("repair-chunks.")], "the temp folder must stay in the scratch folder"
    assert list((tmp_path / "home" / ".Trash").iterdir()) == [] and not (tmp_path / "no-such-drive").exists()
    assert "$HOME/.Trash" not in SCRIPT.read_text()
