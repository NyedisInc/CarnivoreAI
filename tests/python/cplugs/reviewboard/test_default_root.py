
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from src.cplugs.reviewboard import root, store, drafts, wire
from src.cplugs.reviewboard.errors import NoRoot
from src.cplugs.reviewboard.scan import MARKER
from tests.python.cplugs.reviewboard.harness import make_env

MANIFEST = Path(root.__file__).with_name("carnivore.json")


def test_an_unset_setting_makes_and_uses_the_default_folder(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    env.set_root(None)
    ctx = env.host.context("reviewboard", infos=None, background=True)
    path = wire.board_root(ctx)
    assert path == tmp_path / "state" / root.DEFAULT_FOLDER
    assert stat.S_IMODE(path.stat().st_mode) == 0o700 and (path / MARKER).is_file()
    assert wire.board_root(ctx) == path
    status = root.root_status("", tmp_path / "state")
    assert status.ok and status.is_default and status.path == str(path) and not status.warnings


def test_a_set_boards_root_wins(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    ctx = env.host.context("reviewboard", infos=None, background=True)
    assert wire.board_root(ctx) == env.root
    assert not (tmp_path / "state" / root.DEFAULT_FOLDER).exists()
    with pytest.raises(NoRoot) as refused:
        root.resolve_root(str(tmp_path / "nope"), tmp_path / "state")
    assert refused.value.reason == "missing"


def test_a_default_that_cannot_be_made_is_refused(tmp_path: Path) -> None:
    state = tmp_path / "s"
    state.mkdir()
    (state / root.DEFAULT_FOLDER).symlink_to(tmp_path)
    with pytest.raises(NoRoot) as refused:
        root.resolve_root("  ", state)
    assert refused.value.reason == "default_unavailable"


def test_the_manifest_default_is_the_folder_and_does_not_collide_with_drafts_or_locks() -> None:
    declared = {d["id"]: d for d in json.loads(MANIFEST.read_text())["data"]}
    assert declared["boards"]["default"] == root.DEFAULT_FOLDER
    plugin_dirs = {drafts.DRAFT_DIR, store.LOCK_DIR}
    assert root.DEFAULT_FOLDER not in plugin_dirs and "/" not in root.DEFAULT_FOLDER
