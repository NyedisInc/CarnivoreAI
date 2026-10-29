
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

import cryptography  # noqa: F401
import pytest

from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.crate_crypto.age import NONCE_BYTES, SEALED_CHUNK_BYTES
from src.core.crate_crypto.age_header import MAX_HEADER_BYTES, parse_header
from src.core.crate_format import constants as C
from src.core.crate_format.extract import extract_conversation
from src.core.crate_format.reader import open_crate
from src.core.crate_format.verify import expected_from_sidecar, verify
from tests.python.cplugs.crate import golden_build as B
from tests.python.crate_format import golden_read as G
from tests.python.crate_format import mutate
from tests.python.inventory.world import CONV_A

ROOT = Path(__file__).resolve().parents[3]
ANCHORS: Dict[str, str] = {"v1": "e056f49c95a4c7af4a68e8005c0dc4302e35cc9a008255fd2f31758612721366",
                           "v1.1": "6bfae4519ac6f689d3f9788da708400740c9fecab0f86e4e1a0723b0a20fac14"}
CRATES = [fx.name for fx in B.FIXTURES]
PLAIN = [name for name in CRATES if not name.endswith(".age")]
AGE = "session-own.crate.age"
OTHER_SEED = b"some other key, also not a secret"


def _fixture(name: str) -> Path:
    return G.V1 / name


def _cli(tmp_path: Path, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT),
           "CARNIVORE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path)}
    return subprocess.run([sys.executable, "-m", "src.core.crate_format", *args], cwd=ROOT, env=env, input=stdin,
                          capture_output=True, text=True, timeout=300)


def _sums(folder: Path) -> Dict[str, str]:
    out = {}
    for line in (folder / B.SUMS).read_text().splitlines():
        sha, name = line.split("  ", 1)
        out[name] = sha
    return out


def _all_crates() -> List[Path]:
    return sorted(p for p in G.FIXTURES_ROOT.glob("*/*") if p.name.endswith((".crate", ".crate.age")))


def test_sums_cover_and_match_every_file() -> None:
    listed = _sums(G.V1)
    present = {p.relative_to(G.V1).as_posix() for p in G.V1.rglob("*") if p.is_file() and p.name != B.SUMS}
    assert set(listed) == present
    assert {name: G.sha256_file(G.V1 / name) for name in listed} == listed


def test_sums_anchor() -> None:
    for folder, anchor in ANCHORS.items():
        assert hashlib.sha256((G.FIXTURES_ROOT / folder / B.SUMS).read_bytes()).hexdigest() == anchor


@pytest.mark.parametrize("name", CRATES)
def test_each_fixture_passes_drill(name: str, tmp_path: Path) -> None:
    path = _fixture(name)
    expected = expected_from_sidecar(path)
    assert expected == G.sha256_file(path)
    if name in PLAIN:
        report = verify(path, "drill", expected, scratch=tmp_path)
        assert report.ok, report.problems
        return
    assert verify(path, "quick", expected).ok
    report = verify(path, "drill", expected, identity=G.test_identity(), scratch=tmp_path)
    assert report.ok, report.problems
    assert verify(path, "full", expected, identity=G.test_identity(OTHER_SEED)).codes == ["wrong_key"]


@pytest.mark.parametrize("name", CRATES)
def test_listing_equals_expected(name: str) -> None:
    frozen = json.loads((G.V1 / B.EXPECTED / f"{name}.json").read_text())
    assert G.listing(_fixture(name)) == frozen


@pytest.mark.parametrize("name", CRATES)
def test_conversation_extracts_to_the_claude_layout(name: str, tmp_path: Path) -> None:
    path = _fixture(name)
    with open_crate(path, G.identity_for(path)) as reader:
        conv = reader.manifest.conversation(CONV_A)
        records = [r for r in reader.files() if r.conversation_id == CONV_A and r.home == C.HOME_CLAUDE]
        out = extract_conversation(reader, CONV_A, tmp_path / "out", enc_for=slugify_project_dir)
    share = reader.manifest.variant == C.VARIANT_SHARE
    enc = C.SHARED_ENC if share else slugify_project_dir(conv.working_dir)
    assert f"projects/{enc}/{CONV_A}.jsonl" in out.files
    assert any(rel.startswith(f"projects/{enc}/{CONV_A}/") for rel in out.files)
    got = sorted(hashlib.sha256((tmp_path / "out" / rel).read_bytes()).hexdigest() for rel in out.files)
    assert got == sorted(r.content_sha256 for r in records)
    frozen = {f["content_sha256"] for f in json.loads((G.V1 / B.EXPECTED / f"{name}.json").read_text())["files"]}
    assert set(got) <= frozen


@pytest.mark.parametrize("name", CRATES)
def test_cli_verifies_every_fixture(name: str, tmp_path: Path) -> None:
    path = str(_fixture(name))
    if name in PLAIN:
        result = _cli(tmp_path, "verify", path)
        assert result.returncode == 0, result.stdout + result.stderr
        return
    result = _cli(tmp_path, "verify", path, "--identity-stdin", stdin=G.test_identity())
    assert result.returncode == 0, result.stdout + result.stderr
    assert _cli(tmp_path, "verify", path).returncode == 2


@pytest.mark.parametrize("name", PLAIN)
def test_embedded_extract_py_runs_on_its_own(name: str, tmp_path: Path) -> None:
    path = _fixture(name)
    tool = tmp_path / "tool"
    tool.mkdir()
    with open_crate(path) as reader:
        (tool / "extract.py").write_bytes(reader.read_member(C.M_EXTRACT))
        records = reader.files()
    out = tmp_path / "out"
    result = subprocess.run([sys.executable, "-I", "extract.py", str(path), str(out)], cwd=tool, capture_output=True,
                            text=True, timeout=300, env={"PATH": os.environ.get("PATH", "")})
    assert result.returncode == 0, result.stdout + result.stderr
    for r in records:
        home = r.home if r.home_index == 0 else f"{r.home}-{r.home_index}"
        assert G.sha256_file(out / home / r.rel) == r.content_sha256


def test_fixture_versions_only_grow() -> None:
    folders = sorted(p.name for p in G.FIXTURES_ROOT.iterdir() if p.is_dir())
    assert "v1" in folders
    assert all((G.FIXTURES_ROOT / name / B.SUMS).is_file() for name in folders)
    assert set(ANCHORS) == set(folders)


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("golden-rebuilt") / "v1"
    B.build(out)
    return out


@pytest.mark.parametrize("name", CRATES)
def test_format_shape_has_not_drifted(rebuilt: Path, name: str) -> None:
    assert G.shapes(rebuilt / name) == G.shapes(_fixture(name))


def _red_cases(tmp_path: Path) -> List[SimpleNamespace]:
    src = _fixture("project-own.crate")
    with open_crate(src) as reader:
        part = next(m.name for m in reader.members() if m.name.startswith(C.ROWS_PREFIX) and m.name != C.M_SCHEMA)
    cases = [("blob", "flip_blob", {}, "blob_corrupt"), ("files", "flip_member", {"name": C.M_FILES}, "member_mismatch"),
             ("rows", "flip_member", {"name": part}, "member_mismatch"),
             ("drop", "drop", {"name": C.M_PATHS}, "missing_member"),
             ("extra", "add_unlisted", {"name": "lines/claude-history-7.jsonl", "data": b"{}\n"}, "extra_member"),
             ("orphan", "orphan_blob", {}, "extra_blob"), ("too_new", "version", {"major": 2, "minor": 0}, "too_new")]
    out = [SimpleNamespace(name=n, path=mutate.mutate(src, tmp_path / f"{n}.crate", op, **kw), code=code, identity=None)
           for n, op, kw, code in cases]
    age = _fixture(AGE)
    head = parse_header(age.read_bytes()[:MAX_HEADER_BYTES]).length
    at = head + NONCE_BYTES + 2 * SEALED_CHUNK_BYTES
    assert at < age.stat().st_size - SEALED_CHUNK_BYTES
    out.append(SimpleNamespace(name="age_cut", path=mutate.mutate(age, tmp_path / "cut.crate.age", "truncate", at=at),
                               code="age_corrupt", identity=G.test_identity()))
    return out


def test_red_controls(tmp_path: Path) -> None:
    for case in _red_cases(tmp_path):
        report = verify(case.path, "full", G.sha256_file(case.path), identity=case.identity)
        assert not report.ok and case.code in report.codes, (case.name, report.codes)
    too_new = tmp_path / "too_new.crate"
    Path(f"{too_new}.sha256").write_text(f"{G.sha256_file(too_new)}  too_new.crate\n")
    assert _cli(tmp_path, "verify", str(too_new)).returncode == 2
    wrong = tmp_path / "wrong-sidecar.crate"
    wrong.write_bytes(_fixture("project-own.crate").read_bytes())
    Path(f"{wrong}.sha256").write_text(f"{'0' * 64}  wrong-sidecar.crate\n")
    assert verify(wrong, "quick", expected_from_sidecar(wrong)).codes == ["sha_mismatch"]


def test_fixtures_cover_the_v1_vocabulary() -> None:
    seen, required = G.coverage(_all_crates()), B.required_vocabulary()
    frozen = json.loads((G.V1 / B.EXPECTED / "coverage.json").read_text())
    required["entry_stores"] = frozen["required"]["entry_stores"]
    assert B.missing_vocabulary(seen, required) == {}
    assert G.coverage([_fixture(n) for n in CRATES]) == frozen["seen"]


def test_fixtures_hold_no_builder_identity() -> None:
    files = sorted(p for p in G.V1.rglob("*") if p.is_file())
    assert G.identity_hits(files, B.builder_needles()) == []
