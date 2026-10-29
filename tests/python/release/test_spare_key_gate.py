
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GATE = REPO / "scripts" / "release" / "spare_key_gate.py"
TRUST_ROOT = REPO / "src" / "core" / "catalog" / "trust_root.py"
BUILD = REPO / "macOS" / "scripts" / "release-build.sh"
KEYCHAIN_SESSION = REPO / "macOS" / "scripts" / "signing-keychain-session.sh"

_spec = importlib.util.spec_from_file_location("spare_key_gate", GATE)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

PLACEHOLDER_TEXT = "UNSET: the spare index key is not generated yet (Alex, #130)"
A_REAL_KEY = gate._string(
    gate._assignments(gate.ast.parse(TRUST_ROOT.read_text()))["INDEX_PUBLIC_KEY"]
)


ABSENT = object()


def _manifest(path: Path, flag: object = ABSENT) -> Path:
    body = {"name": "carnivore-menubar", "version": "1.16.2"}
    if flag is not ABSENT:
        body["requireSpareIndexKey"] = flag
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def _trust_root(path: Path, spare_expr: str, *, with_placeholder: bool = True) -> Path:
    lines = []
    if with_placeholder:
        lines.append(f"SPARE_INDEX_KEY_PLACEHOLDER: str = (\n    {PLACEHOLDER_TEXT!r}\n)")
    lines.append(f"SPARE_INDEX_PUBLIC_KEY: str = {spare_expr}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize(
    ("spare_expr", "verdict"),
    [
        ("SPARE_INDEX_KEY_PLACEHOLDER", gate.PLACEHOLDER),
        (repr(PLACEHOLDER_TEXT), gate.PLACEHOLDER),
        (repr(A_REAL_KEY), gate.PINNED),
        (f"(\n    {A_REAL_KEY!r}\n)", gate.PINNED),
        (repr("RWnot-a-key"), gate.MALFORMED),
        ("load_key()", gate.MALFORMED),
    ],
    ids=["placeholder-name", "placeholder-text", "pinned", "pinned-parenthesized", "malformed", "expression"],
)
def test_the_verdict_and_both_modes(tmp_path, capsys, spare_expr, verdict):
    path = _trust_root(tmp_path / "trust_root.py", spare_expr)
    required = _manifest(tmp_path / "package.json", True)
    assert gate.spare_key_verdict(path) == verdict
    assert gate.run("release", path, required) == gate.RELEASE_EXIT[verdict]
    assert gate.run("dev", path, required) == 0
    err = capsys.readouterr().err
    if verdict == gate.PINNED:
        assert err == ""
    else:
        assert "REFUSED" in err and "warning" in err


@pytest.mark.parametrize("case", ["missing-file", "no-placeholder", "no-spare", "not-python"])
def test_a_source_it_cannot_judge_is_never_a_pass_in_release(tmp_path, case):
    path = tmp_path / "trust_root.py"
    if case == "no-placeholder":
        _trust_root(path, repr(A_REAL_KEY), with_placeholder=False)
    elif case == "no-spare":
        path.write_text(f"SPARE_INDEX_KEY_PLACEHOLDER = {PLACEHOLDER_TEXT!r}\n")
    elif case == "not-python":
        path.write_text("SPARE_INDEX_PUBLIC_KEY = (\n")
    assert gate.run("release", path, _manifest(tmp_path / "package.json", True)) == 2
    assert gate.run("dev", path) == 0


@pytest.mark.parametrize(
    ("flag", "status"),
    [(ABSENT, 0), (False, 0), (True, 1)],
    ids=["absent-warns-and-passes", "false-warns-and-passes", "true-refuses"],
)
def test_the_placeholder_blocks_a_release_only_when_the_manifest_requires_the_spare(tmp_path, capsys, flag, status):
    path = _trust_root(tmp_path / "trust_root.py", "SPARE_INDEX_KEY_PLACEHOLDER")
    assert gate.run("release", path, _manifest(tmp_path / "package.json", flag)) == status
    err = capsys.readouterr().err
    if status:
        assert "REFUSED" in err and "requireSpareIndexKey is true" in err
    else:
        assert "REFUSED" not in err
        assert "WARNING, RELEASE WITHOUT A SPARE INDEX KEY" in err and "#1947" in err


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_a_flag_that_is_not_a_boolean_is_never_a_pass(tmp_path, flag):
    path = _trust_root(tmp_path / "trust_root.py", "SPARE_INDEX_KEY_PLACEHOLDER")
    assert gate.run("release", path, _manifest(tmp_path / "package.json", flag)) == 2
    assert gate.run("release", path, tmp_path / "missing.json") == 2


def test_a_malformed_spare_refuses_a_release_even_when_not_required(tmp_path):
    path = _trust_root(tmp_path / "trust_root.py", repr("RWnot-a-key"))
    assert gate.run("release", path, _manifest(tmp_path / "package.json")) == 1


def test_a_pinned_spare_never_reads_the_manifest(tmp_path):
    path = _trust_root(tmp_path / "trust_root.py", repr(A_REAL_KEY))
    assert gate.run("release", path, tmp_path / "missing.json") == 0


def test_the_gate_reads_the_shipped_trust_root_the_way_the_app_does():
    from src.core.catalog.trust_root import production_trust_root

    verdict = gate.spare_key_verdict(TRUST_ROOT)
    assert verdict in (gate.PLACEHOLDER, gate.PINNED)
    assert (verdict == gate.PLACEHOLDER) == (production_trust_root().spare_index_key is None)




@pytest.fixture
def build_tree(tmp_path):
    tree = tmp_path / "tree"
    for src, rel in (
        (BUILD, "macOS/scripts/release-build.sh"),
        (KEYCHAIN_SESSION, "macOS/scripts/signing-keychain-session.sh"),
        (BUILD.parent / "pip-audit-lock.sh", "macOS/scripts/pip-audit-lock.sh"),
        (GATE, "scripts/release/spare_key_gate.py"),
    ):
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    _trust_root(tree / "src/core/catalog/trust_root.py", "SPARE_INDEX_KEY_PLACEHOLDER")
    _manifest(tree / "macOS/package.json")
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
    return tree, stubs, home, log


def _run_build(
    build_tree, *, keychain: bool, purpose: str = "", flag: object = ABSENT,
) -> tuple[subprocess.CompletedProcess, str]:
    tree, stubs, home, log = build_tree
    _manifest(tree / "macOS/package.json", flag)
    if keychain:
        (home / "Library" / "Keychains" / "carnivore-signing.keychain-db").write_bytes(b"")
    env = {
        "PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "TMPDIR": str(home),
    }
    if purpose:
        env["CARNIVORE_BUILD_PURPOSE"] = purpose
    done = subprocess.run(
        ["bash", str(tree / "macOS/scripts/release-build.sh")],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    calls = log.read_text() if log.exists() else ""
    return done, calls


def test_a_signing_build_with_the_placeholder_is_refused_before_the_keychain(build_tree):
    done, calls = _run_build(build_tree, keychain=True, flag=True)
    assert done.returncode != 0
    assert "spare_key_gate: REFUSED" in done.stderr
    assert "requireSpareIndexKey is true" in done.stderr
    assert calls == ""


@pytest.mark.parametrize("flag", [ABSENT, False], ids=["absent", "false"])
def test_a_signing_build_not_marked_for_the_spare_warns_and_goes_on(build_tree, flag):
    done, calls = _run_build(build_tree, keychain=True, flag=flag)
    assert "WARNING, RELEASE WITHOUT A SPARE INDEX KEY" in done.stderr
    assert "REFUSED" not in done.stderr
    assert calls != ""


def test_an_ad_hoc_build_with_the_placeholder_only_warns(build_tree):
    done, calls = _run_build(build_tree, keychain=False)
    assert done.returncode == 0, done.stderr
    assert "spare_key_gate: warning" in done.stderr
    assert calls.startswith("npm run package")


def test_the_update_proof_build_only_warns_and_goes_on_to_the_keychain(build_tree):
    done, calls = _run_build(build_tree, keychain=True, purpose="update-proof")
    assert "spare_key_gate: warning" in done.stderr
    assert "REFUSED" not in done.stderr
    assert calls != ""
