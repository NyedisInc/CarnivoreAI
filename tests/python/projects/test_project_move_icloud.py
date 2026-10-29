
from __future__ import annotations

import os
from pathlib import Path

from src.core.project_move import icloud
from src.core.project_move.claude_side import NOT_READ_CLOUD_ONLY
from tests.python.projects.move_world import plan_for


def test_a_folder_move_out_of_icloud_drive_is_refused(world, monkeypatch):
    monkeypatch.setattr(icloud, "icloud_root", lambda: str(world.base / "dev"))
    plan = plan_for(world, move_folder=True)
    failed = [c for c in plan.checks if not c["ok"]]
    assert [c["id"] for c in failed] == ["same_icloud_side"]
    assert "move it in Finder" in failed[0]["message"]


def test_a_move_inside_icloud_drive_passes(world, monkeypatch):
    monkeypatch.setattr(icloud, "icloud_root", lambda: str(world.base))
    assert plan_for(world, move_folder=True).ok


def test_a_repoint_is_not_held_to_the_icloud_line(world, monkeypatch):
    monkeypatch.setattr(icloud, "icloud_root", lambda: str(world.base / "dev"))
    os.rename(world.old, world.new)
    plan = plan_for(world, move_folder=False)
    assert plan.ok, plan.failed()


def test_a_cloud_only_settings_file_is_reported_not_read(world, monkeypatch):
    settings_file = world.old / ".claude" / "settings.json"
    real_lstat = os.lstat

    class Flagged:

        def __init__(self, inner):
            self._inner = inner
            self.st_flags = icloud.SF_DATALESS

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def lstat(path, *args, **kwargs):
        result = real_lstat(path, *args, **kwargs)
        return Flagged(result) if Path(path) == settings_file else result

    opened = []
    real_read = Path.read_text
    monkeypatch.setattr(icloud.os, "lstat", lstat)
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: opened.append(self) or real_read(self, *a, **k))
    plan = plan_for(world, move_folder=True)
    assert plan.informational["settings_files_naming_old_folder"] == [
        {"file": str(settings_file), "not_read": NOT_READ_CLOUD_ONLY}]
    assert settings_file not in opened


def test_dataless_reads_the_flag_without_opening_the_file(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    assert icloud.is_dataless(plain) is False
    assert icloud.read_text_if_local(plain) == "x"
