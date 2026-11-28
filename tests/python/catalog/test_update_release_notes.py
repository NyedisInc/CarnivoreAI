
from pathlib import Path

from src.api.catalog_consent import extract_release_notes


def test_extract_release_notes_from_manifest_string_and_list(tmp_path: Path) -> None:
    (tmp_path / "carnivore.toml").write_text(
        'schema = 2\nid = "demo"\nversion = "1.0.3"\nrelease_notes = ["Added controls bar", "Up arrow rotates clockwise"]\n',
        encoding="utf-8",
    )
    out = extract_release_notes(tmp_path, "1.0.3")
    assert out == "- Added controls bar\n- Up arrow rotates clockwise"


def test_extract_release_notes_from_changelog_version_section(tmp_path: Path) -> None:
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.0.3\n- Added on-screen controls footer\n- Up arrow rotates clockwise\n\n## v1.0.2\n- Added pill icon\n",
        encoding="utf-8",
    )
    out = extract_release_notes(tmp_path, "1.0.3")
    assert out is not None
    assert "Added on-screen controls footer" in out
    assert "Added pill icon" not in out


def test_extract_release_notes_returns_none_when_absent(tmp_path: Path) -> None:
    (tmp_path / "carnivore.toml").write_text('schema = 2\nid = "demo"\nversion = "1.0.3"\n', encoding="utf-8")
    assert extract_release_notes(tmp_path, "1.0.3") is None
