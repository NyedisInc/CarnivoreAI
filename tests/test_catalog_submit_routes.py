
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import pytest

from src.core.catalog import submission_preview

GOOD_MANIFEST = """---
name: my-skill
description: a skill that does a thing worth describing
---

# my skill

do the thing.
"""


def _folder(tmp_path: Path, name: str = "my-skill", manifest: str = GOOD_MANIFEST) -> Path:
    folder = tmp_path / "work" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(manifest)
    return folder


def _codes(preview) -> list:
    return [refusal.code for refusal in preview.refusals]


class TestTheWalker:
    def test_counts_match_disk_and_nested_paths_are_relative(self, tmp_path):
        folder = _folder(tmp_path)
        (folder / "notes").mkdir()
        (folder / "notes" / "extra.md").write_text("x" * 100)
        expected = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        preview = submission_preview.preview_folder(str(folder))
        assert preview.name == "my-skill" and preview.version == "1.0.0"
        assert preview.refusals == []
        assert [f[0] for f in preview.files] == ["SKILL.md", "notes/extra.md"]
        assert preview.total_bytes == expected

    def test_no_manifest_scripts_and_big_file_are_refused(self, tmp_path):
        folder = tmp_path / "work" / "my-skill"
        folder.mkdir(parents=True)
        (folder / "scripts").mkdir()
        (folder / "scripts" / "go.sh").write_text("#!/bin/sh\n")
        (folder / "big.md").write_text("x" * (256 * 1024 + 1))
        preview = submission_preview.preview_folder(str(folder))
        codes = _codes(preview)
        assert "submission_invalid" in codes
        assert "scripts_not_supported" in codes
        named = [r.path for r in preview.refusals if r.code == "body_too_large"]
        assert "big.md" in named

    def test_reserved_and_mismatched_names_are_refused(self, tmp_path):
        reserved = _folder(
            tmp_path, "security-review", GOOD_MANIFEST.replace("my-skill", "security-review")
        )
        assert "name_reserved" in _codes(submission_preview.preview_folder(str(reserved)))
        other = tmp_path / "o"
        other.mkdir()
        mismatch = _folder(other, manifest=GOOD_MANIFEST.replace("name: my-skill", "name: other"))
        assert "submission_invalid" in _codes(submission_preview.preview_folder(str(mismatch)))

    def test_a_symlink_is_refused_and_its_target_never_counted(self, tmp_path):
        folder = _folder(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("SENTINEL-OUTSIDE-THE-FOLDER")
        (folder / "link.md").symlink_to(outside)
        preview = submission_preview.preview_folder(str(folder))
        assert "link.md" in [r.path for r in preview.refusals]
        assert preview.total_bytes == len(GOOD_MANIFEST)

    def test_unreadable_folders_raise(self, tmp_path):
        target = tmp_path / "a-file.md"
        target.write_text("x")
        for bad in (str(tmp_path / "nope"), str(target), "   "):
            with pytest.raises(submission_preview.FolderUnreadable):
                submission_preview.preview_folder(bad)


def _hosted_validator():
    path = ROOT / "hosted" / "catalog" / "api" / "validate_upload.py"
    spec = importlib.util.spec_from_file_location("hosted_validate_upload", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTheLocalRulesMatchTheHostedOnes:

    def test_every_cap_is_the_hosted_one(self):
        from src.core.catalog import submission_rules as local

        hosted = _hosted_validator()
        assert local.MAX_SUBMISSION_BYTES == hosted.MAX_SUBMISSION_BYTES
        assert local.MAX_FILE_BYTES == hosted.MAX_FILE_BYTES
        assert local.MAX_MEMBERS == hosted.MAX_MEMBERS
        assert local.MAX_PATH_LENGTH == hosted.MAX_PATH_LENGTH
        assert local.MAX_DESCRIPTION_CHARS == hosted.MAX_DESCRIPTION_CHARS
        assert local.MANIFEST_NAME == hosted.MANIFEST_NAME
        assert local.DEFAULT_VERSION == hosted.DEFAULT_VERSION

    def test_the_name_grammar_is_the_hosted_one(self):
        from src.core.catalog import submission_rules as local

        hosted = _hosted_validator()
        assert local.SKILL_NAME_RE.pattern == hosted.SKILL_NAME_RE.pattern

    def test_the_reserved_names_are_the_same_set(self):
        from src.core.catalog import submission_rules as local

        hosted = _hosted_validator()
        assert set(local.RESERVED_SKILL_NAMES) == set(hosted.RESERVED_SKILL_NAMES)

    @pytest.mark.parametrize(
        "text",
        [
            GOOD_MANIFEST,
            "---\nname: x\ndescription: y\n---\nbody\n",
            "no front matter at all\n",
            "---\nname: x\n  continued: indented\ndescription: y\n---\nb\n",
            "---\n# a comment\nname: x\ndescription: y\n---\nb\n",
            "---\nname: 'quoted'\ndescription: \"also quoted\"\n---\nb\n",
            "---\nmalformed line with no colon\n---\nb\n",
        ],
    )
    def test_the_front_matter_parser_agrees_with_the_hosted_one(self, text):
        from src.core.catalog import submission_rules as local

        hosted = _hosted_validator()
        assert local.frontmatter(text) == hosted.frontmatter(text)
