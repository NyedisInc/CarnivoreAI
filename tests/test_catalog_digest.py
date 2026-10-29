
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.core.skills.digest import (
    DIGEST_DOMAIN,
    DigestEntry,
    digest_directory,
    digest_entries,
    render_entries,
)

SHA_SKILL_MD = "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
SHA_BIN_RUN = "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb"
FIXED_VECTOR_DIGEST = "27d8ccab232329d1836ed69233bd7508be106c13d8a46c6c8355f904fabd81c5"

FIXED_VECTOR = (
    DigestEntry(relpath="bin/run", mode="100755", sha256=SHA_BIN_RUN),
    DigestEntry(relpath="SKILL.md", mode="100644", sha256=SHA_SKILL_MD),
)


def test_fixed_vector_renders_the_documented_bytes() -> None:
    expected = (
        b"100644\x00SKILL.md\x00"
        + SHA_SKILL_MD.encode("ascii")
        + b"\n"
        + b"100755\x00bin/run\x00"
        + SHA_BIN_RUN.encode("ascii")
        + b"\n"
    )
    assert render_entries(FIXED_VECTOR) == expected


def test_fixed_vector_hashes_to_the_pinned_digest() -> None:
    assert digest_entries(FIXED_VECTOR) == FIXED_VECTOR_DIGEST
    assert (
        hashlib.sha256(DIGEST_DOMAIN + render_entries(FIXED_VECTOR)).hexdigest()
        == FIXED_VECTOR_DIGEST
    )


def test_domain_prefix_is_part_of_the_contract() -> None:
    bare = hashlib.sha256(render_entries(FIXED_VECTOR)).hexdigest()
    assert bare != FIXED_VECTOR_DIGEST


def test_order_is_by_utf8_bytes_not_by_case() -> None:
    entries = [
        DigestEntry(relpath="a.md", mode="100644", sha256="11" * 32),
        DigestEntry(relpath="Z.md", mode="100644", sha256="22" * 32),
        DigestEntry(relpath="é.md", mode="100644", sha256="33" * 32),
    ]
    rendered = render_entries(entries)
    assert rendered.index(b"Z.md") < rendered.index(b"a.md")
    assert rendered.index(b"a.md") < rendered.index("é.md".encode("utf-8"))


def test_digest_is_order_independent() -> None:
    forward = digest_entries(FIXED_VECTOR)
    backward = digest_entries(tuple(reversed(FIXED_VECTOR)))
    assert forward == backward == FIXED_VECTOR_DIGEST


def test_one_byte_of_content_moves_the_digest() -> None:
    changed = (
        FIXED_VECTOR[0],
        DigestEntry(relpath="SKILL.md", mode="100644", sha256="0" + SHA_SKILL_MD[1:]),
    )
    assert digest_entries(changed) != FIXED_VECTOR_DIGEST


def test_the_exec_bit_alone_moves_the_digest() -> None:
    disarmed = (
        DigestEntry(relpath="bin/run", mode="100644", sha256=SHA_BIN_RUN),
        FIXED_VECTOR[1],
    )
    assert digest_entries(disarmed) != FIXED_VECTOR_DIGEST


def test_digest_directory_matches_the_fixed_vector(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_bytes(b"hello\n")
    (tmp_path / "bin").mkdir()
    run = tmp_path / "bin" / "run"
    run.write_bytes(b"#!/bin/sh\nexit 0\n")
    os.chmod(run, 0o755)

    digest, entries = digest_directory(tmp_path)
    assert digest == FIXED_VECTOR_DIGEST
    assert [entry.relpath for entry in entries] == ["SKILL.md", "bin/run"]
    assert [entry.mode for entry in entries] == ["100644", "100755"]


def test_digest_directory_skips_a_symlink(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_bytes(b"hello\n")
    (tmp_path / "link.md").symlink_to(tmp_path / "SKILL.md")

    digest, entries = digest_directory(tmp_path)
    assert [entry.relpath for entry in entries] == ["SKILL.md"]
    assert digest == digest_entries(
        [DigestEntry(relpath="SKILL.md", mode="100644", sha256=SHA_SKILL_MD)]
    )


def test_digest_directory_does_not_descend_a_symlinked_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"secret\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "SKILL.md").write_bytes(b"hello\n")
    (root / "elsewhere").symlink_to(outside, target_is_directory=True)

    _digest, entries = digest_directory(root)
    assert [entry.relpath for entry in entries] == ["SKILL.md"]


def test_digest_directory_skips_a_fifo(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_bytes(b"hello\n")
    os.mkfifo(tmp_path / "pipe")

    _digest, entries = digest_directory(tmp_path)
    assert [entry.relpath for entry in entries] == ["SKILL.md"]


def test_digest_directory_of_an_empty_folder_is_the_domain_alone() -> None:
    assert digest_entries([]) == hashlib.sha256(DIGEST_DOMAIN).hexdigest()


@pytest.mark.parametrize("mode", [0o644, 0o600, 0o664])
def test_only_the_owner_exec_bit_is_read(tmp_path: Path, mode: int) -> None:
    (tmp_path / "SKILL.md").write_bytes(b"hello\n")
    os.chmod(tmp_path / "SKILL.md", mode)
    digest, _entries = digest_directory(tmp_path)
    assert digest == digest_entries(
        [DigestEntry(relpath="SKILL.md", mode="100644", sha256=SHA_SKILL_MD)]
    )
