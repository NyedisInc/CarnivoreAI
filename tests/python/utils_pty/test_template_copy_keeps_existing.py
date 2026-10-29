
from __future__ import annotations

from pathlib import Path

from src.utils.template_manager import copy_templates


def test_existing_file_survives_and_new_file_lands(tmp_path: Path) -> None:
    template = tmp_path / "tpl"
    project = tmp_path / "proj"
    template.mkdir()
    project.mkdir()
    (template / "CLAUDE.md").write_text("template")
    (template / "NEW.md").write_text("new")
    (project / "CLAUDE.md").write_text("mine")

    ok, err = copy_templates(str(template), str(project))

    assert ok and err is None
    assert (project / "CLAUDE.md").read_text() == "mine"
    assert (project / "NEW.md").read_text() == "new"


def test_template_symlink_is_not_followed(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("outside")
    template = tmp_path / "tpl"
    project = tmp_path / "proj"
    template.mkdir()
    (template / "link.txt").symlink_to(secret)

    ok, _ = copy_templates(str(template), str(project))

    assert ok and not (project / "link.txt").exists()
