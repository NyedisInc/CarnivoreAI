
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _seed_scripts(dest: Path) -> None:
    (dest / "scripts" / "lib").mkdir(parents=True)
    (dest / "scripts" / "release").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "__init__.py", dest / "scripts" / "__init__.py")
    for name in ("features.py", "features_schema.py", "features_media.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, dest / "scripts" / name)
    shutil.copy2(
        REPO_ROOT / "scripts" / "release" / "changelog_audit.py",
        dest / "scripts" / "release" / "changelog_audit.py",
    )
    shutil.copytree(
        REPO_ROOT / "scripts" / "lib", dest / "scripts" / "lib", dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


class AuditWorld:

    def __init__(self, root: Path) -> None:
        self.repo = root / "repo"
        self.repo.mkdir()
        (root / "tmp").mkdir()
        (root / "gitconfig").write_text("")
        self.env = {
            **os.environ,
            "HOME": str(root),
            "TMPDIR": str(root / "tmp"),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self._git("init", "--quiet", "-b", "master")
        _seed_scripts(self.repo)
        (self.repo / "features" / "catalog").mkdir(parents=True)
        (self.repo / "features" / "changes").mkdir(parents=True)
        (self.repo / "features" / "areas.json").write_text(
            json.dumps([{"id": "core", "name": "Core", "blurb": "b"}]), encoding="utf-8",
        )
        (self.repo / "features" / "catalog" / "thing.json").write_text(
            json.dumps({
                "id": "thing", "name": "Thing", "summary": "s", "area": "core",
                "status": "stable", "since": "2026-01-01", "updated": "2026-01-01",
            }),
            encoding="utf-8",
        )
        (self.repo / "src").mkdir()
        (self.repo / "docs").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "client").mkdir()
        (self.repo / "client" / "dist").mkdir()
        (self.repo / "macOS").mkdir()
        (self.repo / "macOS" / "package.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8",
        )
        (self.repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        self._commit_all("seed")

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env,
                               capture_output=True, text=True, timeout=30)

    def _commit_all(self, message: str) -> str:
        self._git("add", "-A")
        done = self._git("commit", "--quiet", "-m", message)
        assert done.returncode == 0, done.stdout + done.stderr
        return self._git("rev-parse", "HEAD").stdout.strip()

    def write(self, rel: str, content: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        return self._commit_all(message)

    def audit(self, rev_range: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(self.repo / "scripts" / "release" / "changelog_audit.py"),
             "--range", rev_range, *extra],
            cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=30,
        )


@pytest.fixture
def world(tmp_path: Path) -> AuditWorld:
    return AuditWorld(tmp_path)


def test_clean_range_exits_zero(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("src/app.py", "x = 2\n")
    world.write(
        "features/changes/2026-02-01-1-added-a-thing.json",
        json.dumps({"date": "2026-02-01", "type": "added", "features": ["thing"],
                    "summary": "added a thing", "pr": 1}),
    )
    world.commit("add a thing, with its own change entry")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout


def test_product_commit_with_no_entry_is_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("src/app.py", "x = 2\n")
    sha = world.commit("fix: a real bug nobody logged")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert sha[:10] in proc.stderr
    assert "[fix]" in proc.stderr


def test_docs_only_commit_is_not_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("docs/notes.md", "notes\n")
    world.commit("docs: add notes")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_test_only_commit_is_not_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("tests/test_app.py", "def test_x(): assert True\n")
    world.commit("add a test")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_version_bump_commit_is_not_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("macOS/package.json", json.dumps({"name": "x", "version": "1.0.1"}))
    world.commit("release: bump version to 1.0.1")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_generated_rebuild_commit_is_not_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("client/dist/app.js", "console.log(1)\n")
    world.commit("rebuild generated files")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_small_css_tweak_is_not_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("client/styles.css", ".x { color: red; }\n")
    world.commit("nudge a colour")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_large_css_change_is_still_flagged(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("client/styles.css", "\n".join(f".x{i} {{ color: red; }}" for i in range(60)) + "\n")
    sha = world.commit("large css rewrite")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert sha[:10] in proc.stderr


def test_entry_added_by_a_separate_later_commit_is_a_documented_limitation(world: AuditWorld) -> None:
    base = world._git("rev-parse", "HEAD").stdout.strip()
    world.write("src/feature.py", "y = 1\n")
    code_sha = world.commit("add the feature code")
    world.write(
        "features/changes/2026-02-02-2-added-the-feature.json",
        json.dumps({"date": "2026-02-02", "type": "added", "features": ["thing"],
                    "summary": "added the feature", "pr": 2}),
    )
    world.commit("add the change entry for it")

    proc = world.audit(f"{base}..HEAD")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert code_sha[:10] in proc.stderr


def test_bad_range_cannot_determine(world: AuditWorld) -> None:
    proc = world.audit("nonexistent-ref..HEAD")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "CANNOT DETERMINE" in proc.stderr
