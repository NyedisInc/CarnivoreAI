
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import pytest

from src.core.skills.manifest_preview import (
    CLAUDE_ONLY_FRONTMATTER_KEYS,
    MAX_MANIFEST_TEXT_BYTES,
    PORTABLE_FRONTMATTER_KEYS,
    frontmatter_keys,
    frontmatter_warnings,
    preview_manifest,
)


def folder(tmp_path: Path, manifest: str, **extra: str) -> Path:
    directory = tmp_path / "staged"
    directory.mkdir()
    (directory / "SKILL.md").write_text(manifest, encoding="utf-8")
    for name, text in extra.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory




def test_the_manifest_text_comes_back_whole_and_unmarked(tmp_path):
    manifest = "---\nname: review\ndescription: does a thing\n---\n\n# review\n"
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert preview.skill_md_text == manifest
    assert preview.skill_md_truncated is False


def test_every_file_is_listed_with_its_size_and_the_total_adds_up(tmp_path):
    staged = folder(
        tmp_path,
        "# review\n",
        **{"reference.md": "a" * 40, "deep/inner.md": "b" * 7},
    )

    preview = preview_manifest(staged)

    assert [entry.relpath for entry in preview.files] == [
        "SKILL.md",
        "deep/inner.md",
        "reference.md",
    ]
    sizes = {entry.relpath: entry.size for entry in preview.files}
    assert sizes["reference.md"] == 40
    assert sizes["deep/inner.md"] == 7
    assert sizes["SKILL.md"] == len("# review\n")
    assert preview.total_bytes == sum(entry.size for entry in preview.files)


def test_a_manifest_over_the_cap_is_cut_and_says_so(tmp_path):
    manifest = "x" * (MAX_MANIFEST_TEXT_BYTES + 500)
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert preview.skill_md_truncated is True
    assert len(preview.skill_md_text) == MAX_MANIFEST_TEXT_BYTES
    assert preview.files[0].size == len(manifest)
    assert preview.total_bytes == len(manifest)


def test_a_manifest_exactly_at_the_cap_is_not_marked_truncated(tmp_path):
    manifest = "y" * MAX_MANIFEST_TEXT_BYTES
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert preview.skill_md_truncated is False
    assert preview.skill_md_text == manifest


def test_a_folder_with_no_manifest_raises(tmp_path):
    directory = tmp_path / "empty"
    directory.mkdir()

    with pytest.raises(FileNotFoundError):
        preview_manifest(directory)




def test_a_claude_only_key_is_warned_about_and_left_in_place(tmp_path):
    manifest = (
        "---\nname: review\ndescription: d\nuser-invocable: false\n---\n# review\n"
    )
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert len(preview.frontmatter_warnings) == 1
    assert "user-invocable" in preview.frontmatter_warnings[0]
    assert "Codex ignores it" in preview.frontmatter_warnings[0]
    assert (staged / "SKILL.md").read_text(encoding="utf-8") == manifest


def test_the_other_claude_only_key_is_warned_about_too(tmp_path):
    manifest = "---\nname: r\ndisable-model-invocation: true\n---\n# r\n"
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert len(preview.frontmatter_warnings) == 1
    assert "disable-model-invocation" in preview.frontmatter_warnings[0]


def test_an_unknown_key_is_warned_about_as_unrecognised_not_stripped(tmp_path):
    manifest = "---\nname: r\nsomething-new: 4\n---\n# r\n"
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert len(preview.frontmatter_warnings) == 1
    assert "something-new" in preview.frontmatter_warnings[0]
    assert "either harness defines" in preview.frontmatter_warnings[0]
    assert (staged / "SKILL.md").read_text(encoding="utf-8") == manifest


def test_the_two_warning_classes_read_differently(tmp_path):
    manifest = "---\nuser-invocable: true\nmystery: 1\n---\n# r\n"
    staged = folder(tmp_path, manifest)

    warnings = preview_manifest(staged).frontmatter_warnings

    assert len(warnings) == 2
    assert warnings[0] != warnings[1]
    assert "Claude Code front-matter key" in warnings[0]
    assert "either harness defines" in warnings[1]


def test_every_portable_key_is_silent(tmp_path):
    manifest = (
        "---\n"
        "name: review\n"
        "description: d\n"
        "license: MIT\n"
        "compatibility: any\n"
        "allowed-tools:\n  - Bash\n"
        "metadata:\n  tier: 1\n"
        "---\n# review\n"
    )
    staged = folder(tmp_path, manifest)

    preview = preview_manifest(staged)

    assert preview.frontmatter_warnings == ()
    assert set(frontmatter_keys(manifest)) == set(PORTABLE_FRONTMATTER_KEYS)


def test_the_two_key_sets_do_not_overlap():
    assert PORTABLE_FRONTMATTER_KEYS & CLAUDE_ONLY_FRONTMATTER_KEYS == frozenset()


def test_a_manifest_with_no_front_matter_warns_about_nothing(tmp_path):
    staged = folder(tmp_path, "# review\n\nsome prose\n")

    assert preview_manifest(staged).frontmatter_warnings == ()


def test_malformed_front_matter_answers_no_keys_and_never_raises(tmp_path):
    staged = folder(tmp_path, "---\nname: [unclosed\n---\n# r\n")

    preview = preview_manifest(staged)

    assert preview.frontmatter_warnings == ()
    assert preview.skill_md_text.startswith("---")


def test_front_matter_that_is_not_a_mapping_answers_no_keys():
    assert frontmatter_keys("---\n- one\n- two\n---\nbody\n") == ()
    assert frontmatter_warnings("---\n- one\n---\nbody\n") == ()


def test_the_keys_come_back_in_document_order(tmp_path):
    manifest = "---\nzeta: 1\nname: r\nalpha: 2\n---\n# r\n"

    assert frontmatter_keys(manifest) == ("zeta", "name", "alpha")
    warnings = frontmatter_warnings(manifest)
    assert "zeta" in warnings[0]
    assert "alpha" in warnings[1]
