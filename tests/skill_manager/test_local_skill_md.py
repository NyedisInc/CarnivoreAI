
from __future__ import annotations

import os

import pytest

from src.core.skill_manager.local_skill_md import read_location_skill_md
from src.core.skill_manager.scan import MAX_SKILL_MD_BYTES
from src.core.skill_manager.types import OverrideError


def _root(tmp_path):
    path = tmp_path / "skills"
    path.mkdir()
    return {"path": str(path), "is_symlink": False}, path


def test_reads_and_caps(tmp_path):
    root, path = _root(tmp_path)
    (path / "big").mkdir()
    (path / "big" / "SKILL.md").write_text("x" * (MAX_SKILL_MD_BYTES + 10))
    text, truncated, size = read_location_skill_md({"folder": "big"}, root)
    assert truncated is True and len(text) == MAX_SKILL_MD_BYTES and size == MAX_SKILL_MD_BYTES + 10


def test_a_skill_md_link_out_of_its_folder_is_refused(tmp_path):
    root, path = _root(tmp_path)
    (path / "evil").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    os.symlink(secret, path / "evil" / "SKILL.md")
    with pytest.raises(OverrideError) as exc:
        read_location_skill_md({"folder": "evil"}, root)
    assert exc.value.code == "target_unsafe"


def test_a_folder_link_out_of_the_root_is_refused(tmp_path):
    root, path = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("hi")
    os.symlink(outside, path / "linked")
    with pytest.raises(OverrideError):
        read_location_skill_md({"folder": "linked"}, root)
