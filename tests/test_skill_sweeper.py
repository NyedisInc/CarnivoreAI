
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.sessions.ports import InstallRoots, Target
from src.core.skills import targets as skill_targets
from src.core.skills.plan_tokens import MAX_OUTSTANDING_TOKENS
from src.core.skills.sweeper import (
    MAX_CONCURRENT_STAGING,
    STAGING_TTL_SECONDS,
    TRASH_TTL_SECONDS,
    SkillSweeper,
    sweep_directory,
)


class FakeInstallRoots:

    def __init__(self, base: Path) -> None:
        self.base = base

    def targets_for(self, kind: str, scope: str, project_path) -> tuple:
        return (
            Target(harness="claude", leaf_dir=self.base / "claude" / "skills"),
            Target(harness="codex", leaf_dir=self.base / "codex" / "skills"),
        )

    def required_manifest(self, kind: str) -> str:
        return "SKILL.md"

    def trash_dir(
        self, harness: str, scope: str, project_path: str | None
    ) -> Path:
        for target in self.targets_for("skill", scope, project_path):
            if target.harness == harness:
                return target.leaf_dir.parent / ".carnivore-trash"
        raise ValueError(f"unknown harness {harness!r}")

    def staging_dir(self) -> Path:
        return self.base / "state" / "skills" / ".staging"

    def pending_dir(self) -> Path:
        return self.base / "state" / "skills" / ".pending"

    def root_listing(self, harness: str) -> tuple:
        root = self.base / harness / "skills"
        if not root.is_dir():
            return ()
        return tuple(sorted(p.name for p in root.iterdir()))

    def read_only_listing(self, harness: str) -> tuple:
        return ()

    def present_harnesses(self) -> tuple:
        return ("claude", "codex")

    def legacy_targets_for(self, kind: str, scope: str, project_path) -> tuple:
        return ()


@pytest.fixture()
def roots(tmp_path) -> FakeInstallRoots:
    return FakeInstallRoots(tmp_path)


def _aged_dir(parent: Path, name: str, age_seconds: float) -> Path:
    path = parent / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "marker").write_text("x\n")
    when = time.time() - age_seconds
    os.utime(path, (when, when))
    return path


def test_the_fake_satisfies_the_port():
    assert isinstance(FakeInstallRoots(Path("/tmp")), InstallRoots)




def test_an_entry_older_than_the_ttl_is_removed(tmp_path):
    old = _aged_dir(tmp_path / "staging", "stale", 7200)

    removed = sweep_directory(tmp_path / "staging", 3600, time.time())

    assert removed == 1
    assert not old.exists()


def test_an_entry_younger_than_the_ttl_is_left(tmp_path):
    fresh = _aged_dir(tmp_path / "staging", "in-use", 60)

    removed = sweep_directory(tmp_path / "staging", 3600, time.time())

    assert removed == 0
    assert fresh.exists()


def test_an_absent_directory_is_zero_removals_and_not_an_error(tmp_path):
    assert sweep_directory(tmp_path / "never-created", 3600, time.time()) == 0


def test_the_sweep_is_one_level_deep(tmp_path):
    fresh = _aged_dir(tmp_path / "staging", "fresh", 10)
    nested = _aged_dir(fresh, "very-old-child", 999999)

    sweep_directory(tmp_path / "staging", 3600, time.time())

    assert nested.exists()


def test_a_symlink_entry_is_unlinked_and_never_followed(tmp_path):
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep-me").write_text("important\n")

    staging = tmp_path / "staging"
    staging.mkdir()
    link = staging / "a-link"
    link.symlink_to(outside, target_is_directory=True)
    when = time.time() - 999999
    os.utime(link, (when, when), follow_symlinks=False)

    removed = sweep_directory(staging, 3600, time.time())

    assert removed == 1
    assert not link.exists()
    assert (outside / "keep-me").is_file()


def test_the_write_guard_is_called_on_every_removal(tmp_path, monkeypatch):
    seen: list[str] = []
    real_guard = skill_targets.assert_test_write_allowed

    def recording_guard(path: Path) -> None:
        seen.append(str(path))
        real_guard(path)

    monkeypatch.setattr(skill_targets, "assert_test_write_allowed", recording_guard)

    _aged_dir(tmp_path / "staging", "one", 999999)
    _aged_dir(tmp_path / "staging", "two", 999999)

    removed = sweep_directory(tmp_path / "staging", 3600, time.time())

    assert removed == 2
    assert sorted(seen) == [
        str(tmp_path / "staging" / "one"),
        str(tmp_path / "staging" / "two"),
    ]


def test_the_guard_recorder_would_notice_a_missing_call(tmp_path, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        skill_targets,
        "assert_test_write_allowed",
        lambda path: seen.append(str(path)),
    )

    import shutil

    from src.core.skills import sweeper as sweeper_module

    monkeypatch.setattr(sweeper_module, "remove_tree", shutil.rmtree)

    _aged_dir(tmp_path / "staging", "one", 999999)
    removed = sweep_directory(tmp_path / "staging", 3600, time.time())

    assert removed == 1
    assert seen == []




def test_a_sweep_reaps_staging_and_both_harness_trashes(roots):
    _aged_dir(roots.staging_dir(), "stale-preview", STAGING_TTL_SECONDS + 60)
    _aged_dir(
        roots.trash_dir("claude", "global", None),
        "old-claude",
        TRASH_TTL_SECONDS + 60,
    )
    _aged_dir(
        roots.trash_dir("codex", "global", None),
        "old-codex",
        TRASH_TTL_SECONDS + 60,
    )

    sweeper = SkillSweeper(install_roots=roots)
    result = asyncio.run(sweeper.sweep_now())

    assert result == {"staging_removed": 1, "trash_removed": 2}


def test_the_two_cutoffs_are_different_and_the_longer_one_is_the_trash(roots):
    age = STAGING_TTL_SECONDS + 60
    assert age < TRASH_TTL_SECONDS

    staged = _aged_dir(roots.staging_dir(), "debris", age)
    displaced = _aged_dir(
        roots.trash_dir("claude", "global", None), "user-folder", age
    )

    asyncio.run(SkillSweeper(install_roots=roots).sweep_now())

    assert not staged.exists()
    assert displaced.exists()


def test_the_sweeper_touches_nothing_in_the_skills_roots_themselves(roots):
    installed = _aged_dir(
        roots.base / "claude" / "skills", "ancient-skill", 99999999
    )

    asyncio.run(SkillSweeper(install_roots=roots).sweep_now())

    assert installed.exists()


def test_a_boot_pass_hook_exists_and_sweeps(roots):
    assert callable(SkillSweeper.run_boot_pass)

    _aged_dir(roots.staging_dir(), "stale", STAGING_TTL_SECONDS + 60)
    result = asyncio.run(SkillSweeper(install_roots=roots).run_boot_pass())

    assert result["staging_removed"] == 1


def test_the_run_loop_sweeps_at_boot_before_its_first_sleep(roots):
    stale = _aged_dir(roots.staging_dir(), "stale", STAGING_TTL_SECONDS + 60)

    async def drive() -> None:
        sweeper = SkillSweeper(install_roots=roots, interval_seconds=9999)
        task = asyncio.create_task(sweeper.run())
        for _ in range(200):
            if not stale.exists():
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())

    assert not stale.exists()


def test_the_run_loop_reraises_cancellation(roots):

    async def drive() -> None:
        sweeper = SkillSweeper(install_roots=roots, interval_seconds=9999)
        task = asyncio.create_task(sweeper.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())


def test_the_concurrent_staging_cap_is_a_published_number():
    assert isinstance(MAX_CONCURRENT_STAGING, int)
    assert MAX_CONCURRENT_STAGING > 0


def test_the_plan_token_cap_sits_strictly_under_the_staging_cap():
    assert MAX_OUTSTANDING_TOKENS == MAX_CONCURRENT_STAGING - 2
    assert MAX_OUTSTANDING_TOKENS < MAX_CONCURRENT_STAGING
    assert MAX_OUTSTANDING_TOKENS > 0
