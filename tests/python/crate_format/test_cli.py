
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from src.core.crate_crypto.keys import generate
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import CONV, build_crate

ROOT = Path(__file__).resolve().parents[3]
CHECK = ("import sys; from src.core.crate_format.__main__ import main; rc = main(sys.argv[1:]); "
         "assert not [m for m in sys.modules if m.split('.')[0] in ('fastapi', 'uvicorn', 'pydantic') "
         "or m.startswith(('src.api', 'src.cplugs'))], 'a server module was imported'; sys.exit(rc)")


def run(tmp_path: Path, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT),
           "CARNIVORE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path)}
    return subprocess.run([sys.executable, "-c", CHECK, *args], cwd=ROOT, env=env, input=stdin, capture_output=True,
                          text=True, timeout=120)


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    path = build_crate(tmp_path / "a.crate")
    Path(f"{path}.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  a.crate\n")
    return path


def test_verify_ok_from_the_sidecar(tmp_path: Path, plain: Path) -> None:
    for level in ("quick", "full", "drill"):
        result = run(tmp_path, "verify", str(plain), "--level", level)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().splitlines()[-1].startswith("ok level")
    assert not (tmp_path / "state").exists() and not (tmp_path / "home").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("carnivore-crate-drill-")]


def test_verify_problems_exit_1(tmp_path: Path, plain: Path) -> None:
    bad = mutate.mutate(plain, tmp_path / "bad.crate", "flip_blob")
    result = run(tmp_path, "verify", str(bad), "--sha", hashlib.sha256(bad.read_bytes()).hexdigest())
    assert result.returncode == 1 and "problem blob_corrupt" in result.stdout


def test_verify_without_expected_hash_exits_2(tmp_path: Path) -> None:
    path = build_crate(tmp_path / "nosidecar.crate")
    result = run(tmp_path, "verify", str(path))
    assert result.returncode == 2 and "no_expected_hash" in result.stdout


def test_too_new_exits_2(tmp_path: Path, plain: Path) -> None:
    new = mutate.mutate(plain, tmp_path / "new.crate", "version", major=2, minor=0)
    result = run(tmp_path, "verify", str(new), "--sha", hashlib.sha256(new.read_bytes()).hexdigest())
    assert result.returncode == 2 and "too_new" in result.stdout


def test_unreadable_exits_2(tmp_path: Path) -> None:
    assert run(tmp_path, "verify", str(tmp_path / "missing.crate"), "--sha", "0" * 64).returncode == 2
    assert run(tmp_path, "list", str(tmp_path / "missing.crate")).returncode == 2


def test_age_identity_from_stdin(tmp_path: Path) -> None:
    identity, recipient = generate()
    path = build_crate(tmp_path / "a.crate.age", recipients=[recipient])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    ok = run(tmp_path, "verify", str(path), "--sha", sha, "--identity-stdin", stdin=f"# key\n{identity}\n")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert identity not in ok.stdout + ok.stderr
    assert run(tmp_path, "verify", str(path), "--sha", sha).returncode == 2
    assert run(tmp_path, "verify", str(path), "--sha", sha, "--level", "quick").returncode == 0
    listed = run(tmp_path, "list", str(path), "--identity-stdin", stdin=identity)
    assert listed.returncode == 0 and f"conversation {CONV}" in listed.stdout
    assert run(tmp_path, "list", str(path)).returncode == 2


def test_list_and_extract(tmp_path: Path, plain: Path) -> None:
    listed = run(tmp_path, "list", str(plain))
    assert listed.returncode == 0 and "files 8" in listed.stdout and "rows huddle.db messages 1" in listed.stdout
    dest = tmp_path / "out"
    extracted = run(tmp_path, "extract", str(plain), CONV, str(dest))
    assert extracted.returncode == 0 and f"resume: claude --resume {CONV}" in extracted.stdout
    assert (dest / "projects" / "-Users-x-app" / f"{CONV}.jsonl").is_file()
    again = run(tmp_path, "extract", str(plain), CONV, str(dest))
    assert again.returncode == 1 and "destination_exists" in again.stderr


def _embedded_extract(tmp_path: Path, crate: Path) -> subprocess.CompletedProcess:
    import tarfile

    tool = tmp_path / "tool"
    tool.mkdir()
    with tarfile.open(crate, "r:") as tar:
        (tool / "extract.py").write_bytes(tar.extractfile("extract.py").read())
    return subprocess.run([sys.executable, "-I", str(tool / "extract.py"), str(crate), str(tmp_path / "rebuilt")],
                          cwd=tool, capture_output=True, text=True, timeout=120)


def test_embedded_extract_py_runs_on_its_own(tmp_path: Path, plain: Path) -> None:
    result = _embedded_extract(tmp_path, plain)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "rebuilt" / "claude" / "projects" / "-Users-x-app" / f"{CONV}.jsonl").is_file()
    assert result.stdout.count("\nok ") + result.stdout.startswith("ok ") == 8


def test_embedded_extract_py_reports_a_mismatch(tmp_path: Path, plain: Path) -> None:
    bad = mutate.mutate(plain, tmp_path / "bad.crate", "flip_blob")
    result = _embedded_extract(tmp_path, bad)
    assert result.returncode == 1 and "MISMATCH" in result.stdout
