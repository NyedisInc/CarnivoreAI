
from __future__ import annotations

import gzip
import io
import os
import re
import stat
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.skills.digest import digest_directory
from src.core.skills.validate import (
    ARCHIVE_INVALID,
    SCRIPTS_NOT_SUPPORTED,
    ArchiveRefused,
    Limits,
    ValidatedArchive,
    ValidatedMember,
    duplicate_key,
    validate_archive,
)
from src.core.skills.stage import (
    EXEC_FILE_MODE,
    FILE_MODE,
    _target_path,
    member_mode,
    stage_archive,
)

PREFIX = "repo-abc123/"
PUBLISHER = "pub"
NAME = "name"
SKILL = f"{PREFIX}skills/{PUBLISHER}/{NAME}/"

MANIFEST = (f"{SKILL}SKILL.md", b"# a skill\n", {})


def make_tar(members: list[tuple[str, bytes | None, dict]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, body, options in members:
            info = tarfile.TarInfo(name)
            info.type = options.get("type", tarfile.REGTYPE)
            info.mode = options.get("mode", 0o644)
            if "linkname" in options:
                info.linkname = options["linkname"]
            if info.type == tarfile.REGTYPE:
                data = body or b""
                info.size = options.get("size", len(data))
                tar.addfile(info, io.BytesIO(data))
            else:
                info.size = options.get("size", 0)
                tar.addfile(info)
    return buffer.getvalue()


def tar_path(
    tmp_path: Path, members: list[tuple[str, bytes | None, dict]], name: str = "a.tar.gz"
) -> Path:
    path = tmp_path / name
    path.write_bytes(make_tar(members))
    return path


def refusal(path: Path, **kwargs) -> ArchiveRefused:
    with pytest.raises(ArchiveRefused) as caught:
        validate_archive(path, publisher=PUBLISHER, name=NAME, **kwargs)
    return caught.value


def relpaths(path: Path, **kwargs) -> list[str]:
    archive = validate_archive(path, publisher=PUBLISHER, name=NAME, **kwargs)
    return [member.relpath for member in archive.members]




@pytest.mark.parametrize(
    "options, word",
    [
        ({"type": tarfile.SYMTYPE, "linkname": "../../../../etc/passwd"}, "symlink"),
        ({"type": tarfile.LNKTYPE, "linkname": f"{SKILL}SKILL.md"}, "hard link"),
        ({"type": tarfile.CHRTYPE}, "character device"),
        ({"type": tarfile.BLKTYPE}, "block device"),
        ({"type": tarfile.FIFOTYPE}, "fifo"),
    ],
)
def test_non_regular_members_are_refused(
    tmp_path: Path, options: dict, word: str
) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}thing", None, options)])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert word in caught.detail
    assert "thing" in caught.detail


def test_a_directory_member_is_ignored_not_refused(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [
            (f"{SKILL[:-1]}", None, {"type": tarfile.DIRTYPE, "mode": 0o755}),
            MANIFEST,
            (f"{SKILL}sub", None, {"type": tarfile.DIRTYPE, "mode": 0o755}),
            (f"{SKILL}sub/a.md", b"a\n", {}),
        ],
    )
    assert relpaths(path) == ["SKILL.md", "sub/a.md"]




def test_an_absolute_member_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, ("/etc/passwd", b"root\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "absolute" in caught.detail


def test_a_parent_segment_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}../../escape.md", b"x\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert ".." in caught.detail


def test_a_member_outside_the_prefix_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, ("other-repo/x.md", b"x\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "prefix" in caught.detail


def test_a_non_ascii_member_name_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}café.md", b"x\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "non-ASCII" in caught.detail


def test_duplicate_after_case_folding_is_refused(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}Readme.md", b"a\n", {}), (f"{SKILL}readme.md", b"b\n", {})],
    )
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "duplicate" in caught.detail


def test_duplicate_after_nfc_collides_on_the_key(tmp_path: Path) -> None:
    precomposed = "café.md"
    decomposed = "café.md"
    assert precomposed != decomposed
    assert duplicate_key(precomposed) == duplicate_key(decomposed)

    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}{precomposed}", b"a\n", {}),
         (f"{SKILL}{decomposed}", b"b\n", {})],
    )
    assert refusal(path).code == ARCHIVE_INVALID




def test_a_nested_manifest_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}sub/SKILL.md", b"# no\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "nested" in caught.detail


def test_a_folder_with_no_manifest_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [(f"{SKILL}README.md", b"# hi\n", {})])
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "SKILL.md" in caught.detail


def test_an_empty_archive_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [])
    assert refusal(path).code == ARCHIVE_INVALID




def test_a_scripts_member_is_refused_with_its_own_code(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}scripts/x.sh", b"echo\n", {})])
    caught = refusal(path)
    assert caught.code == SCRIPTS_NOT_SUPPORTED
    assert "scripts/x.sh" in caught.detail


def test_an_exec_bit_member_is_refused_with_its_own_code(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}tool", b"echo\n", {"mode": 0o755})])
    caught = refusal(path)
    assert caught.code == SCRIPTS_NOT_SUPPORTED
    assert "executable" in caught.detail




def test_more_members_than_the_cap_is_refused(tmp_path: Path) -> None:
    members = [MANIFEST]
    members.extend((f"{SKILL}f{index:05d}.md", b"x", {}) for index in range(2000))
    path = tar_path(tmp_path, members)
    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "2000" in caught.detail


def test_header_sizes_over_the_cap_are_refused(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}a.bin", b"x" * 1500, {}), (f"{SKILL}b.bin", b"y" * 1500, {})],
    )
    caught = refusal(path, limits=Limits(max_bytes=2048))
    assert caught.code == ARCHIVE_INVALID
    assert "header sizes" in caught.detail


def test_bytes_that_arrive_over_the_cap_are_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}a.bin", b"x" * 4096, {})])
    caught = refusal(path, limits=Limits(max_bytes=3000))
    assert caught.code == ARCHIVE_INVALID


def test_the_decompressed_stream_cap_stops_a_bomb_outside_the_folder(
    tmp_path: Path,
) -> None:
    members = [MANIFEST, (f"{PREFIX}other/big.bin", b"\0" * 200_000, {})]
    path = tar_path(tmp_path, members)

    assert relpaths(path) == ["SKILL.md"]

    caught = refusal(path, limits=Limits(max_archive_bytes=60_000))
    assert caught.code == ARCHIVE_INVALID
    assert "stream cap" in caught.detail


def test_a_header_that_claims_more_than_the_stream_holds_is_refused(
    tmp_path: Path,
) -> None:
    info = tarfile.TarInfo(f"{SKILL}SKILL.md")
    info.size = 4096
    stream = info.tobuf() + b"abcd" + b"\0" * 508 + b"\0" * 1024
    path = tmp_path / "lying.tar.gz"
    path.write_bytes(gzip.compress(stream))

    caught = refusal(path)
    assert caught.code == ARCHIVE_INVALID
    assert "unreadable archive" in caught.detail


def test_a_truncated_gzip_stream_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST])
    path.write_bytes(path.read_bytes()[:40])
    assert refusal(path).code == ARCHIVE_INVALID


def test_the_default_limits_are_the_documented_numbers() -> None:
    limits = Limits()
    assert limits.max_members == 2000
    assert limits.max_bytes == 10 * 1024 * 1024
    assert limits.max_archive_bytes == 64 * 1024 * 1024




def test_noise_is_dropped_and_never_enters_the_digest(tmp_path: Path) -> None:
    noisy = tar_path(
        tmp_path,
        [
            MANIFEST,
            (f"{SKILL}.DS_Store", b"\0\0", {}),
            (f"{SKILL}._SKILL.md", b"\0\0", {}),
            (f"{SKILL}__MACOSX/x", b"\0\0", {}),
            (f"{SKILL}.git/config", b"[core]\n", {}),
            (f"{PREFIX}.git/HEAD", b"ref\n", {}),
        ],
        name="noisy.tar.gz",
    )
    clean = tar_path(tmp_path, [MANIFEST], name="clean.tar.gz")

    assert relpaths(noisy) == ["SKILL.md"]
    assert validate_archive(
        noisy, publisher=PUBLISHER, name=NAME
    ).digest == validate_archive(clean, publisher=PUBLISHER, name=NAME).digest


def test_the_exec_bit_rule_does_not_fire_on_dropped_noise(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path, [MANIFEST, (f"{SKILL}.git/hooks/pre-commit", b"x\n", {"mode": 0o755})]
    )
    assert relpaths(path) == ["SKILL.md"]


def test_other_skills_in_the_same_tarball_are_skipped(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [
            MANIFEST,
            (f"{PREFIX}skills/other/thing/SKILL.md", b"# other\n", {}),
            (f"{PREFIX}skills/{PUBLISHER}/name-extra/SKILL.md", b"# near\n", {}),
            (f"{PREFIX}README.md", b"# repo\n", {}),
            (f"{PREFIX}skills/other/thing/scripts/run.sh", b"x\n", {"mode": 0o755}),
        ],
    )
    assert relpaths(path) == ["SKILL.md"]


def test_the_prefix_and_skill_root_are_reported(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST])
    archive = validate_archive(path, publisher=PUBLISHER, name=NAME)
    assert archive.prefix == PREFIX
    assert archive.skill_root == SKILL
    assert archive.total_bytes == len(MANIFEST[1])




def valid_tree(tmp_path: Path) -> Path:
    return tar_path(
        tmp_path,
        [
            MANIFEST,
            (f"{SKILL}reference/notes.md", b"notes\n", {}),
            (f"{SKILL}reference/deep/more.md", b"more\n", {}),
        ],
        name="valid.tar.gz",
    )


def test_staging_writes_the_members_and_matches_the_digest(tmp_path: Path) -> None:
    archive_path = valid_tree(tmp_path)
    dest = tmp_path / "staged"

    staged = stage_archive(archive_path, dest, publisher=PUBLISHER, name=NAME)

    assert staged.path == dest
    assert (dest / "SKILL.md").read_bytes() == b"# a skill\n"
    assert (dest / "reference" / "deep" / "more.md").read_bytes() == b"more\n"
    assert staged.digest == staged.archive.digest
    assert digest_directory(dest)[0] == staged.digest


def test_every_written_file_is_0o644_and_every_parent_is_0o700(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "staged"
    previous = os.umask(0o077)
    try:
        stage_archive(valid_tree(tmp_path), dest, publisher=PUBLISHER, name=NAME)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert stat.S_IMODE((dest / "reference").stat().st_mode) == 0o700
    assert stat.S_IMODE((dest / "reference" / "deep").stat().st_mode) == 0o700
    for name in ("SKILL.md", "reference/notes.md", "reference/deep/more.md"):
        assert stat.S_IMODE((dest / name).stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "mode, allow_scripts, expected, claim",
    [
        (
            "100755",
            False,
            FILE_MODE,
            "THE FLAG HALF: a publisher's exec bit decides nothing while "
            "the caller has not unlocked executable content",
        ),
        (
            "100644",
            False,
            FILE_MODE,
            "an ordinary file in a locked staging is an ordinary file",
        ),
        (
            "100755",
            True,
            EXEC_FILE_MODE,
            "the one case that gets 0o755",
        ),
        (
            "100644",
            True,
            FILE_MODE,
            "THE MODE HALF: an unlocked staging does not make the manifest "
            "executable, which would change what the folder hashes to",
        ),
    ],
)
def test_the_mode_decision_needs_both_halves(
    mode: str, allow_scripts: bool, expected: int, claim: str
) -> None:
    member = ValidatedMember(
        relpath="scripts/run.sh", size=12, mode=mode, sha256="0" * 64
    )

    assert member_mode(member, allow_scripts=allow_scripts) == expected, claim


def test_an_existing_destination_is_refused(tmp_path: Path) -> None:
    dest = tmp_path / "staged"
    dest.mkdir()
    with pytest.raises(FileExistsError) as caught:
        stage_archive(valid_tree(tmp_path), dest, publisher=PUBLISHER, name=NAME)
    assert "staging directory already exists" in str(caught.value)


def test_a_failure_after_the_first_write_removes_the_whole_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.core.skills.stage.digest_directory",
        lambda root: ("00" * 32, ()),
    )
    dest = tmp_path / "staged"
    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(valid_tree(tmp_path), dest, publisher=PUBLISHER, name=NAME)
    assert caught.value.code == ARCHIVE_INVALID
    assert "does not match the validated digest" in caught.value.detail
    assert not dest.exists()


def test_the_join_refuses_a_path_that_leaves_the_destination(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "staged"
    for hostile in ("../escape.md", "sub/../../escape.md", "."):
        with pytest.raises(ArchiveRefused) as caught:
            _target_path(dest, hostile)
        assert caught.value.code == ARCHIVE_INVALID


def test_a_refused_archive_leaves_nothing_behind(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}link", None, {"type": tarfile.SYMTYPE, "linkname": "/etc"})],
    )
    dest = tmp_path / "staged"
    with pytest.raises(ArchiveRefused):
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)
    assert not dest.exists()


def test_an_exec_bit_archive_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}tool", b"echo\n", {"mode": 0o755})])
    dest = tmp_path / "staged"
    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)
    assert caught.value.code == SCRIPTS_NOT_SUPPORTED
    assert not dest.exists()


def _verdict_with(tmp_path: Path, mutate) -> None:
    real = validate_archive(valid_tree(tmp_path), publisher=PUBLISHER, name=NAME)
    import src.core.skills.stage as stage_module

    original = stage_module.validate_archive
    stage_module.validate_archive = lambda *a, **k: mutate(real)
    try:
        stage_archive(
            valid_tree(tmp_path), tmp_path / "staged", publisher=PUBLISHER, name=NAME
        )
    finally:
        stage_module.validate_archive = original


def test_a_member_that_grew_between_the_two_passes_is_refused(tmp_path: Path) -> None:

    def shrink(archive: ValidatedArchive) -> ValidatedArchive:
        first = archive.members[0]
        smaller = ValidatedMember(
            relpath=first.relpath,
            size=first.size - 1,
            mode=first.mode,
            sha256=first.sha256,
        )
        return replace(archive, members=(smaller,) + archive.members[1:])

    with pytest.raises(ArchiveRefused) as caught:
        _verdict_with(tmp_path, shrink)
    assert caught.value.code == ARCHIVE_INVALID
    assert "grew between passes" in caught.value.detail
    assert not (tmp_path / "staged").exists()


def test_a_member_that_vanished_between_the_two_passes_is_refused(
    tmp_path: Path,
) -> None:

    def add_ghost(archive: ValidatedArchive) -> ValidatedArchive:
        ghost = ValidatedMember(
            relpath="ghost.md", size=3, mode="100644", sha256="ee" * 32
        )
        return replace(archive, members=archive.members + (ghost,))

    with pytest.raises(ArchiveRefused) as caught:
        _verdict_with(tmp_path, add_ghost)
    assert caught.value.code == ARCHIVE_INVALID
    assert "changed between passes" in caught.value.detail
    assert not (tmp_path / "staged").exists()


def test_the_writer_never_reaches_for_the_library_helpers() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "core"
        / "skills"
        / "stage.py"
    ).read_text()
    assert "extractall" not in source
    assert re.search(r"\.extract\(", source) is None
    assert "extractfile" in source




def pax_tar_path(tmp_path: Path, header_name: str, pax_path: str) -> Path:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        manifest = tarfile.TarInfo(MANIFEST[0])
        manifest.size = len(MANIFEST[1])
        tar.addfile(manifest, io.BytesIO(MANIFEST[1]))
        info = tarfile.TarInfo(header_name)
        info.size = 2
        info.pax_headers = {"path": pax_path}
        tar.addfile(info, io.BytesIO(b"x\n"))
    path = tmp_path / "pax.tar.gz"
    path.write_bytes(buffer.getvalue())
    return path


def test_a_doubled_slash_at_the_skill_root_is_refused(tmp_path: Path) -> None:
    escape = tmp_path / "outside.md"
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}{escape}", b"owned\n", {})])

    caught = refusal(path)

    assert caught.code == ARCHIVE_INVALID
    assert not escape.exists()


def test_the_writer_refuses_the_doubled_slash_member_too(tmp_path: Path) -> None:
    escape = tmp_path / "outside.md"
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}{escape}", b"owned\n", {})])
    dest = tmp_path / "staged"

    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)

    assert caught.value.code == ARCHIVE_INVALID
    assert not escape.exists()
    assert not dest.exists()


def test_two_spellings_of_one_path_are_refused_not_collided(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}a/b", b"one\n", {}), (f"{SKILL}a//b", b"two\n", {})],
    )
    dest = tmp_path / "staged"

    assert refusal(path).code == ARCHIVE_INVALID
    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)

    assert caught.value.code == ARCHIVE_INVALID
    assert not dest.exists()


def test_a_regular_file_named_like_a_directory_is_refused(tmp_path: Path) -> None:
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}sub/", b"", {}), (f"{SKILL}sub/x", b"x\n", {})],
    )
    dest = tmp_path / "staged"

    assert refusal(path).code == ARCHIVE_INVALID
    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)

    assert caught.value.code == ARCHIVE_INVALID
    assert not dest.exists()


def test_a_member_named_dot_at_the_skill_root_is_refused(tmp_path: Path) -> None:
    path = tar_path(tmp_path, [MANIFEST, (f"{SKILL}.", b"", {})])

    caught = refusal(path)

    assert caught.code == ARCHIVE_INVALID


def test_a_nul_smuggled_through_a_pax_header_is_refused(tmp_path: Path) -> None:
    path = pax_tar_path(tmp_path, f"{SKILL}plain.md", f"{SKILL}nul\x00.md")

    caught = refusal(path)

    assert caught.code == ARCHIVE_INVALID
    assert "NUL" in caught.detail


def test_a_collision_the_validator_missed_is_a_refusal_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.core.skills.validate.unsafe_relpath_reason", lambda relpath, name: None
    )
    path = tar_path(
        tmp_path,
        [MANIFEST, (f"{SKILL}a/b", b"one\n", {}), (f"{SKILL}a//b", b"two\n", {})],
    )
    dest = tmp_path / "staged"

    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(path, dest, publisher=PUBLISHER, name=NAME)

    assert caught.value.code == ARCHIVE_INVALID
    assert "collide" in caught.value.detail
    assert not dest.exists()




def _cplug_tar(tmp_path: Path, folder: str) -> Path:
    root = f"{PREFIX}{folder}/{PUBLISHER}/{NAME}/"
    return tar_path(tmp_path, [(f"{root}cplug.json", b"{}\n", {})])


@pytest.mark.parametrize("folder", ["plugins", "cplugs"])
def test_a_cplug_installs_from_the_folder_its_src_path_names(
    tmp_path: Path, folder: str
) -> None:
    path = _cplug_tar(tmp_path, folder)
    staged = stage_archive(
        path, tmp_path / "staged", publisher=PUBLISHER, name=NAME,
        kind="cplug", src_path=f"{folder}/{PUBLISHER}/{NAME}",
    )
    assert (staged.path / "cplug.json").is_file()


@pytest.mark.parametrize(
    "src_path", ["skills/pub/name", "plugins/pub/other", "plugins/pub/name/x"]
)
def test_a_src_path_outside_the_kinds_folders_is_refused(
    tmp_path: Path, src_path: str
) -> None:
    path = _cplug_tar(tmp_path, "plugins")
    with pytest.raises(ArchiveRefused) as caught:
        stage_archive(
            path, tmp_path / "staged", publisher=PUBLISHER, name=NAME,
            kind="cplug", src_path=src_path,
        )
    assert caught.value.code == ARCHIVE_INVALID
