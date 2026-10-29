
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from src.core.pack.skills import watch

pytestmark = pytest.mark.skipif(not hasattr(__import__("select"), "kqueue"), reason="kqueue only")


def make_skill(root: Path) -> Path:
    skill = root / "demo"
    (skill / "scripts" / "deep").mkdir(parents=True)
    (skill / "__pycache__").mkdir()
    (skill / "SKILL.md").write_text("one")
    (skill / "scripts" / "deep" / "tool.py").write_text("a")
    return skill


def atomic_save(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


async def run_case(tmp_path: Path, max_dirs: int):
    root = tmp_path / "skills"
    skill = make_skill(root)
    fired: list[int] = []
    w = watch.SkillsWatcher(lambda: {"claude": root}, lambda: {("claude", "demo")}, lambda: fired.append(1),
                            quiet_seconds=0.05, max_dirs=max_dirs)
    assert w.start()
    await w.rearm()
    return root, skill, fired, w


def test_nested_rename_save_fires_once_and_pycache_none(tmp_path: Path) -> None:
    async def go() -> None:
        _root, skill, fired, w = await run_case(tmp_path, 512)
        try:
            assert not w.shallow
            (skill / "__pycache__" / "m.pyc").write_text("x")
            await asyncio.sleep(0.4)
            assert fired == []
            atomic_save(skill / "scripts" / "deep" / "tool.py", "b")
            atomic_save(skill / "scripts" / "deep" / "tool.py", "c")
            await asyncio.sleep(0.4)
            assert fired == [1]
        finally:
            w.close()

    asyncio.run(go())


def test_over_the_bound_falls_back_to_top_folders(tmp_path: Path) -> None:
    async def go() -> None:
        _root, skill, fired, w = await run_case(tmp_path, 2)
        try:
            assert w.shallow
            atomic_save(skill / "SKILL.md", "two")
            await asyncio.sleep(0.4)
            assert fired == [1]
        finally:
            w.close()

    asyncio.run(go())


def test_raise_open_file_limit_never_lowers() -> None:
    import resource

    before = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    watch.raise_open_file_limit(64)
    assert resource.getrlimit(resource.RLIMIT_NOFILE)[0] >= min(before, before)
