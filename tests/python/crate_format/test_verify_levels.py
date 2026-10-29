
from __future__ import annotations

import hashlib
import os
from collections import namedtuple
from pathlib import Path
from typing import Callable, List

import pytest

from src.core.crate_crypto.age import NONCE_BYTES, SEALED_CHUNK_BYTES
from src.core.crate_crypto.age_header import MAX_HEADER_BYTES, parse_header
from src.core.crate_crypto.keys import generate
from src.core.crate_format import canonical, verify_full
from src.core.crate_format.verify import PROBLEM_CODES, VerifyReport, expected_from_sidecar, verify
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import SrcFile, build_crate, default_files

Pairs = List[mutate.Pair]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def broken(tmp_path: Path, change: Callable[[Pairs], None]) -> Path:
    pairs = mutate.entries(build_crate(tmp_path / "good.crate"))
    change(pairs)
    return mutate.write(pairs, tmp_path / "bad.crate")


def check(path: Path, level: str = "full", **kw) -> VerifyReport:
    return verify(path, level, sha(path), scratch=path.parent / "scratch", **kw)


@pytest.mark.parametrize("level", ["quick", "full", "drill"])
@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_good_crate_passes_every_level(tmp_path: Path, level: str, codec: str) -> None:
    path = build_crate(tmp_path / "a.crate", codec=codec, target=64)
    report = check(path, level)
    assert report.ok, report.problems
    assert report.format_version == (1, 0) and report.bundle_sha256 == sha(path)
    if level != "quick":
        assert report.files_checked == 8 and report.blobs_checked > 8 and report.members_checked == 11
    assert not (tmp_path / "scratch").exists() or not any((tmp_path / "scratch").iterdir())


def test_no_expected_hash_is_a_problem_never_a_pass(tmp_path: Path) -> None:
    report = verify(build_crate(tmp_path / "a.crate"), "full")
    assert report.codes == ["no_expected_hash"] and not report.ok


def test_sha_mismatch_and_the_sidecar(tmp_path: Path) -> None:
    path = build_crate(tmp_path / "a.crate")
    assert verify(path, "quick", "0" * 64).codes == ["sha_mismatch"]
    assert expected_from_sidecar(path) is None
    Path(f"{path}.sha256").write_text(f"{sha(path)}  a.crate\n")
    assert expected_from_sidecar(path) == sha(path)


Case = namedtuple("Case", "change level code")
CASES = {
    "malformed": Case(lambda p: mutate.find(p, "crate.json").__setitem__(1, b"{not json"), "quick", "malformed"),
    "too_new": Case(lambda p: (mutate.set_manifest(p, {**mutate.manifest(p), "format_version": [2, 0]})), "quick",
                    "too_new"),
    "missing_member": Case(lambda p: p.remove(mutate.find(p, "paths.jsonl")), "quick", "missing_member"),
    "extra_member": Case(lambda p: _extra_member(p), "quick", "extra_member"),
    "member_mismatch": Case(lambda p: _flip(p, "files.jsonl"), "full", "member_mismatch"),
    "rows_part_flip": Case(lambda p: _flip(p, "rows/huddle.db/messages.jsonl"), "full", "member_mismatch"),
    "blob_corrupt": Case(lambda p: _flip(p, "blob"), "full", "blob_corrupt"),
    "missing_blob": Case(lambda p: (p.remove(mutate.find(p, "blob")), mutate.reseal(p)), "full", "missing_blob"),
    "missing_blob_quick": Case(lambda p: p.remove(mutate.find(p, "blob")), "quick", "missing_blob"),
    "extra_blob": Case(lambda p: _orphan(p), "quick", "extra_blob"),
    "extra_blob_full": Case(lambda p: (_orphan(p), mutate.reseal(p)), "full", "extra_blob"),
    "chain_mismatch": Case(lambda p: mutate.edit_files(p, lambda r: r[0].__setitem__("chain_sha256", "a" * 64)),
                           "full", "chain_mismatch"),
    "content_mismatch": Case(lambda p: mutate.edit_files(p, lambda r: r[0].__setitem__("content_sha256", "b" * 64)),
                             "full", "content_mismatch"),
    "length_mismatch": Case(lambda p: mutate.edit_files(p, lambda r: r[0].__setitem__("length", 1)),
                            "full", "content_mismatch"),
    "rows_mismatch": Case(lambda p: _schema_rows(p, 99), "full", "rows_mismatch"),
    "content_id_mismatch": Case(lambda p: mutate.set_manifest(p, {**mutate.manifest(p), "content_id": "c" * 64}),
                                "full", "content_id_mismatch"),
}


def _flip(pairs: Pairs, name: str) -> None:
    pair = mutate.find(pairs, name)
    pair[1] = mutate.flip(pair[1])


def _extra_member(pairs: Pairs) -> None:
    mutate.insert_before_manifest(pairs, mutate.info("lines/codex-session-index-0.jsonl"), b"{}\n")


def _orphan(pairs: Pairs) -> None:
    from src.core.blobcodec.codec import blob_relpath, compress

    raw = b"an orphan chunk"
    mutate.insert_before_manifest(pairs, mutate.info(blob_relpath(hashlib.sha256(raw).hexdigest(), "zstd")),
                                  compress(raw, "zstd"))


def _schema_rows(pairs: Pairs, rows: int) -> None:
    pair = mutate.find(pairs, "rows/schema.json")
    obj = canonical.loads(pair[1])
    obj["stores"]["huddle.db"]["tables"]["messages"]["rows"] = rows
    pair[1] = canonical.dumps(obj)
    mutate.reseal(pairs)


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_fault_reports_its_own_code(tmp_path: Path, name: str) -> None:
    case = CASES[name]
    report = check(broken(tmp_path, case.change), case.level)
    assert not report.ok and case.code in report.codes, report.problems


def test_every_problem_code_is_exercised() -> None:
    covered = {case.code for case in CASES.values()} | {
        "no_expected_hash", "sha_mismatch", "needs_identity", "wrong_key", "age_corrupt", "no_space"}
    assert covered == set(PROBLEM_CODES)


@pytest.fixture
def age_crate(tmp_path: Path):
    identity, recipient = generate()
    return build_crate(tmp_path / "a.crate.age", recipients=[recipient]), identity


def test_age_without_identity(age_crate) -> None:
    path, _ = age_crate
    quick = verify(path, "quick", sha(path))
    assert quick.ok and quick.encrypted
    assert verify(path, "full", sha(path)).codes == ["needs_identity"]
    assert verify(path, "drill", sha(path), scratch=path.parent / "s").codes == ["needs_identity"]


def test_age_with_identity_passes_drill(age_crate) -> None:
    path, identity = age_crate
    report = verify(path, "drill", sha(path), identity=identity, scratch=path.parent / "s")
    assert report.ok and report.files_checked == 8
    proof = verify(path, "full", sha(path), extra_identities=[identity])
    assert proof.ok


def test_age_wrong_key(age_crate) -> None:
    path, _ = age_crate
    other, _ = generate()
    assert verify(path, "full", sha(path), identity=other).codes == ["wrong_key"]


def test_age_truncated_at_a_chunk_boundary(tmp_path: Path) -> None:
    identity, recipient = generate()
    files = default_files() + [SrcFile("file_history", "claude", "file-history/big/blob", os.urandom(300_000))]
    path = build_crate(tmp_path / "big.crate.age", files=files, recipients=[recipient])
    head = parse_header(path.read_bytes()[:MAX_HEADER_BYTES]).length
    at = head + NONCE_BYTES + 2 * SEALED_CHUNK_BYTES
    assert at < path.stat().st_size - SEALED_CHUNK_BYTES
    cut = mutate.mutate(path, tmp_path / "cut.crate.age", "truncate", at=at)
    assert "age_corrupt" in verify(cut, "full", sha(cut), identity=identity).codes
    assert verify(cut, "quick", sha(path)).codes == ["sha_mismatch"]


def test_drill_without_space_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = build_crate(tmp_path / "a.crate")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(verify_full.shutil, "disk_usage", lambda _p: usage(1, 1, 0))
    assert check(path, "drill").codes == ["no_space"]


def test_drill_needs_scratch_and_levels_are_known(tmp_path: Path) -> None:
    path = build_crate(tmp_path / "a.crate")
    with pytest.raises(ValueError):
        verify(path, "drill", sha(path))
    with pytest.raises(ValueError):
        verify(path, "deep", sha(path))


def test_age_cut_inside_a_tag_fails_the_keyless_layout_check(age_crate, tmp_path: Path) -> None:
    path, _ = age_crate
    head = parse_header(path.read_bytes()[:MAX_HEADER_BYTES]).length
    cut = mutate.mutate(path, tmp_path / "mid.crate.age", "truncate", at=head + NONCE_BYTES + 10)
    assert verify(cut, "quick", sha(cut)).codes == ["age_corrupt"]
