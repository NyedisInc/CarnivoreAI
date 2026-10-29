
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()

BASE_AREA = {"id": "core", "name": "Core", "blurb": "b"}
BASE_ENTRY = {
    "id": "thing", "name": "Thing", "summary": "s", "area": "core",
    "status": "stable", "since": "2026-01-01", "updated": "2026-01-01",
}


def _seed_scripts(dest: Path) -> None:
    (dest / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "__init__.py", dest / "scripts" / "__init__.py")
    for name in ("features.py", "features_schema.py", "features_media.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, dest / "scripts" / name)
    (dest / "scripts" / "release").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "scripts" / "release" / "changelog_audit.py",
        dest / "scripts" / "release" / "changelog_audit.py",
    )
    shutil.copytree(
        REPO_ROOT / "scripts" / "lib", dest / "scripts" / "lib", dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _bare_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    _seed_scripts(repo)
    (repo / "features" / "catalog").mkdir(parents=True)
    (repo / "features" / "changes").mkdir(parents=True)
    return repo


def _check(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(repo / "scripts" / "features.py"), "check", *args],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )




def test_this_repos_own_features_pass_check() -> None:
    proc = subprocess.run(
        ["python3", str(REPO_ROOT / "scripts" / "features.py"), "check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr



_REPO_PATH_PREFIXES = ("src/", "web/", "client/", "macOS/", "docs/", "features/", "scripts/", "tests/")


def _looks_like_repo_path(value: str) -> bool:
    return "/" in value and value.startswith(_REPO_PATH_PREFIXES)


def _dangling_repo_paths(repo: Path, entry: dict) -> list[str]:
    missing = []
    for field in ("surfaces", "api_routes", "docs"):
        for value in entry.get(field, []):
            if isinstance(value, str) and _looks_like_repo_path(value) and not (repo / value).exists():
                missing.append(f"{entry.get('id', '?')}.{field}: {value}")
    return missing


def test_catalog_repo_paths_point_at_real_code() -> None:
    missing: list[str] = []
    for path in sorted((REPO_ROOT / "features" / "catalog").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        missing.extend(_dangling_repo_paths(REPO_ROOT, entry))
    assert not missing, "catalog entries pointing at code that does not exist:\n" + "\n".join(missing)


def test_catalog_repo_path_check_is_proven_able_to_fail(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")

    real_entry = {"id": "thing", "surfaces": ["src/real.py"], "api_routes": [], "docs": []}
    assert _dangling_repo_paths(tmp_path, real_entry) == []

    fake_entry = {"id": "thing", "surfaces": ["src/api/does-not-exist-anywhere.py"], "api_routes": [], "docs": []}
    missing = _dangling_repo_paths(tmp_path, fake_entry)
    assert missing == ["thing.surfaces: src/api/does-not-exist-anywhere.py"]

    label_entry = {"id": "thing", "surfaces": ["agents drawer row"], "api_routes": [], "docs": []}
    assert _dangling_repo_paths(tmp_path, label_entry) == []




def test_check_passes_on_a_valid_minimal_fixture(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    proc = _check(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_check_fails_on_an_unknown_area(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", {**BASE_ENTRY, "area": "ghost-area"})
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "ghost-area" in proc.stderr and "not listed" in proc.stderr


def test_check_fails_on_a_dangling_feature_id(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    _write(repo / "features" / "changes" / "2026-01-02-1-x.json",
           {"date": "2026-01-02", "type": "fixed", "features": ["ghost-feature"], "summary": "s"})
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "ghost-feature" in proc.stderr


def test_check_fails_when_id_does_not_match_filename(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", {**BASE_ENTRY, "id": "other-thing"})
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "does not match filename" in proc.stderr


def test_check_fails_on_a_bad_enum(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", {**BASE_ENTRY, "status": "not-a-real-status"})
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "status" in proc.stderr and "not-a-real-status" in proc.stderr


def test_check_fails_on_a_duplicate_area_id(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA, {**BASE_AREA, "name": "Core Two"}])
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "duplicate area id" in proc.stderr


def test_check_fails_on_malformed_json_rather_than_crashing(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    (repo / "features" / "areas.json").write_text("[not valid json", encoding="utf-8")
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "invalid JSON" in proc.stderr


def test_check_requires_non_empty_features_unless_internal(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    _write(repo / "features" / "changes" / "2026-01-02-1-x.json",
           {"date": "2026-01-02", "type": "fixed", "features": [], "summary": "s"})
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "internal" in proc.stderr

    _write(repo / "features" / "changes" / "2026-01-02-1-x.json",
           {"date": "2026-01-02", "type": "internal", "features": [], "summary": "s"})
    proc = _check(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr




def test_new_change_writes_a_correctly_named_valid_file(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    proc = subprocess.run(
        ["python3", str(repo / "scripts" / "features.py"), "new-change",
         "--type", "fixed", "--features", "thing", "--summary", "fix the thing",
         "--pr", "42", "--issue", "41", "--date", "2026-01-03"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    files = list((repo / "features" / "changes").glob("*.json"))
    assert len(files) == 1, files
    assert files[0].name.startswith("2026-01-03-42-"), files[0].name
    entry = json.loads(files[0].read_text())
    assert entry == {
        "date": "2026-01-03", "type": "fixed", "features": ["thing"],
        "summary": "fix the thing", "issue": 41, "pr": 42,
    }
    assert _check(repo).returncode == 0


def test_new_change_without_a_pr_drops_the_pr_from_name_and_entry(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    proc = subprocess.run(
        ["python3", str(repo / "scripts" / "features.py"), "new-change",
         "--type", "fixed", "--features", "thing", "--summary", "fix the thing",
         "--date", "2026-01-03"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    files = list((repo / "features" / "changes").glob("*.json"))
    assert [f.name for f in files] == ["2026-01-03-fix-the-thing.json"]
    assert "pr" not in json.loads(files[0].read_text())
    assert _check(repo).returncode == 0


def test_new_change_refuses_when_features_missing_and_not_internal(tmp_path: Path) -> None:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", BASE_ENTRY)
    proc = subprocess.run(
        ["python3", str(repo / "scripts" / "features.py"), "new-change",
         "--type", "fixed", "--summary", "no features given", "--pr", "1"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not list((repo / "features" / "changes").glob("*.json"))




def _schema_errors(record: dict, schema: dict) -> list[str]:
    errors = []
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in record:
            errors.append(f"missing required field {name!r}")
    if schema.get("additionalProperties") is False:
        errors += [f"unknown field {k!r}" for k in record if k not in props]
    for name, value in record.items():
        prop = props.get(name)
        if prop is not None:
            errors += _value_errors(value, prop, name)
    return errors


def _value_errors(value, prop: dict, where: str) -> list[str]:
    errors = []
    kind = prop.get("type")
    if kind == "string" and not isinstance(value, str):
        errors.append(f"{where}: expected a string")
    elif kind == "array":
        if not isinstance(value, list):
            errors.append(f"{where}: expected an array")
        else:
            item_schema = prop.get("items", {})
            errors += [e for i, item in enumerate(value) for e in _value_errors(item, item_schema, f"{where}[{i}]")]
    elif kind == "boolean" and not isinstance(value, bool):
        errors.append(f"{where}: expected a boolean")
    elif kind == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        errors.append(f"{where}: expected an integer")
    if isinstance(value, str):
        if "enum" in prop and value not in prop["enum"]:
            errors.append(f"{where}: {value!r} not in {prop['enum']}")
        if "pattern" in prop and not re.match(prop["pattern"], value):
            errors.append(f"{where}: {value!r} does not match {prop['pattern']!r}")
    return errors


def test_schema_walk_catches_a_bad_record() -> None:
    fragment = {
        "type": "object", "additionalProperties": False, "required": ["id"],
        "properties": {"id": {"type": "string", "pattern": "^[a-z]+$"}},
    }
    assert _schema_errors({"id": "ok"}, fragment) == []
    assert _schema_errors({}, fragment) != []
    assert _schema_errors({"id": "NOT-OK"}, fragment) != []
    assert _schema_errors({"id": "ok", "extra": 1}, fragment) != []




def _git(cwd: Path, env: dict, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


class FeaturesWorld:

    def __init__(self, root: Path) -> None:
        self.root = root
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
            "CLOUDE_TRUNK_REMOTE": "origin",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.origin = root / "origin.git"
        _git(root, self.env, "init", "--quiet", "--bare", "-b", "master", str(self.origin))

        seed = root / "seed"
        _git(root, self.env, "init", "--quiet", "-b", "master", str(seed))
        _seed_scripts(seed)
        (seed / "features" / "catalog").mkdir(parents=True)
        (seed / "features" / "changes").mkdir(parents=True)
        _write(seed / "features" / "areas.json", [BASE_AREA])
        _write(seed / "features" / "catalog" / "thing.json", BASE_ENTRY)
        (seed / "src").mkdir()
        (seed / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        (seed / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
        _git(seed, self.env, "add", "-A")
        _git(seed, self.env, "commit", "--quiet", "-m", "seed")
        _git(seed, self.env, "remote", "add", "origin", str(self.origin))
        _git(seed, self.env, "push", "--quiet", "origin", "master")
        self.hub = self.clone("hub")

    def clone(self, name: str) -> Path:
        path = self.root / name
        _git(self.root, self.env, "clone", "--quiet", str(self.origin), str(path))
        return path

    def branch(self, clone: Path, name: str) -> None:
        _git(clone, self.env, "checkout", "--quiet", "-b", name)

    def commit_all(self, clone: Path, message: str) -> None:
        _git(clone, self.env, "add", "-A")
        _git(clone, self.env, "commit", "--quiet", "-m", message)

    def push(self, clone: Path, branch: str) -> None:
        _git(clone, self.env, "push", "--quiet", "origin", branch)

    def merge(self, branch: str) -> None:
        _git(self.hub, self.env, "fetch", "--quiet", "origin")
        _git(self.hub, self.env, "checkout", "--quiet", "--force", "-B", "master", "origin/master")
        _git(self.hub, self.env, "merge", "--quiet", "--no-ff", "--no-edit", f"origin/{branch}")
        _git(self.hub, self.env, "push", "--quiet", "origin", "master")

    def tag(self, name: str) -> None:
        _git(self.hub, self.env, "fetch", "--quiet", "origin")
        _git(self.hub, self.env, "checkout", "--quiet", "--force", "--detach", "origin/master")
        _git(self.hub, self.env, "tag", name)
        _git(self.hub, self.env, "push", "--quiet", "origin", name)

    def features_py(self, cwd: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(cwd / "scripts" / "features.py"), *args],
            cwd=cwd, env=self.env, capture_output=True, text=True, timeout=30,
        )


@pytest.fixture
def world(tmp_path: Path) -> FeaturesWorld:
    return FeaturesWorld(tmp_path)


def test_branch_check_requires_a_change_file_for_a_product_diff(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/1-x")
    (worker / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    world.commit_all(worker, "touch src")
    refused = world.features_py(worker, "check", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "features/changes/" in refused.stderr

    added = world.features_py(worker, "new-change", "--type", "fixed", "--features", "thing",
                               "--summary", "fix it", "--pr", "1", "--date", "2026-01-05")
    assert added.returncode == 0, added.stdout + added.stderr
    world.commit_all(worker, "add change entry")
    passed = world.features_py(worker, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_refuses_a_misnamed_change_file(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/3-name")
    entry = {"date": "2026-01-05", "type": "internal", "features": [], "summary": "x"}
    (worker / "features" / "changes").mkdir(parents=True, exist_ok=True)
    _write(worker / "features" / "changes" / "20260105-bad-name.json", entry)
    world.commit_all(worker, "add a misnamed entry")
    refused = world.features_py(worker, "check", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "20260105-bad-name.json" in refused.stderr


def test_branch_check_passes_with_no_product_diff(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/2-docs")
    (worker / "NOTES.md").write_text("hi\n", encoding="utf-8")
    world.commit_all(worker, "add a note")
    passed = world.features_py(worker, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_allows_an_internal_entry_with_no_features(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/3-refactor")
    (worker / "src" / "app.py").write_text("x = 3\n", encoding="utf-8")
    added = world.features_py(worker, "new-change", "--type", "internal",
                               "--summary", "refactor internals", "--pr", "3", "--date", "2026-01-06")
    assert added.returncode == 0, added.stdout + added.stderr
    world.commit_all(worker, "refactor plus internal change entry")
    passed = world.features_py(worker, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_requires_an_updated_bump_on_a_changed_catalog_file(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/4-catalog")
    _write(worker / "features" / "catalog" / "thing.json", {**BASE_ENTRY, "summary": "a new summary"})
    world.commit_all(worker, "edit catalog, forget to bump updated")
    refused = world.features_py(worker, "check", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "updated" in refused.stderr

    _write(worker / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "a new summary", "updated": "2026-01-07"})
    world.commit_all(worker, "bump updated")
    passed = world.features_py(worker, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_allows_a_same_day_re_edit_with_unchanged_updated(world: FeaturesWorld) -> None:
    today = _utc_today()
    worker1 = world.clone("worker1")
    world.branch(worker1, "feat/10-first-edit")
    _write(worker1 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "first edit today", "updated": today})
    world.commit_all(worker1, "stamp updated to today")
    world.push(worker1, "feat/10-first-edit")
    world.merge("feat/10-first-edit")

    worker2 = world.clone("worker2")
    world.branch(worker2, "feat/11-second-edit")
    _write(worker2 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "second edit, same day", "updated": today})
    world.commit_all(worker2, "edit again the same day, no later date exists")
    passed = world.features_py(worker2, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_same_day_rule_reads_the_commit_date_in_utc(world: FeaturesWorld) -> None:
    stamped = "2026-03-10"
    world.env.update({
        "TZ": "America/New_York",
        "GIT_AUTHOR_DATE": "2026-03-09T21:30:00-0400",
        "GIT_COMMITTER_DATE": "2026-03-09T21:30:00-0400",
    })
    worker1 = world.clone("worker1")
    world.branch(worker1, "feat/14-first-edit")
    _write(worker1 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "first edit", "updated": stamped})
    world.commit_all(worker1, "stamp updated to the UTC day")
    world.push(worker1, "feat/14-first-edit")
    world.merge("feat/14-first-edit")

    worker2 = world.clone("worker2")
    world.branch(worker2, "feat/15-second-edit")
    _write(worker2 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "second edit, same UTC day", "updated": stamped})
    world.commit_all(worker2, "edit again the same UTC day")
    passed = world.features_py(worker2, "check", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_check_refuses_an_unchanged_date_that_is_not_today(world: FeaturesWorld) -> None:
    stale_date = "2020-01-01"
    worker1 = world.clone("worker1")
    world.branch(worker1, "feat/12-stamp-old")
    _write(worker1 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "old stamp", "updated": stale_date})
    world.commit_all(worker1, "stamp an old date")
    world.push(worker1, "feat/12-stamp-old")
    world.merge("feat/12-stamp-old")

    worker2 = world.clone("worker2")
    world.branch(worker2, "feat/13-edit-no-bump")
    _write(worker2 / "features" / "catalog" / "thing.json",
           {**BASE_ENTRY, "summary": "edited but date left old", "updated": stale_date})
    world.commit_all(worker2, "edit catalog, leave old date")
    refused = world.features_py(worker2, "check", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "updated" in refused.stderr


def test_branch_check_cannot_determine_on_master(world: FeaturesWorld) -> None:
    on_master = world.features_py(world.hub, "check", "--branch")
    assert on_master.returncode == 2, on_master.stdout + on_master.stderr


def test_render_hides_internal_changes_from_the_visible_log_but_keeps_them_in_index(
    world: FeaturesWorld,
) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/5-mixed")
    for args in (
        ("--type", "added", "--features", "thing", "--summary", "a visible change",
         "--pr", "5", "--date", "2026-01-10"),
        ("--type", "internal", "--summary", "quiet refactor", "--pr", "5",
         "--date", "2026-01-10", "--slug", "quiet-refactor"),
    ):
        proc = world.features_py(worker, "new-change", *args)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(worker, "mixed change entries")
    world.push(worker, "feat/5-mixed")
    world.merge("feat/5-mixed")

    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    md = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    assert "a visible change" in md
    assert "quiet refactor" not in md

    index = json.loads((world.hub / "features" / "index.json").read_text(encoding="utf-8"))
    summaries = {c["summary"] for c in index["changes"]}
    assert "a visible change" in summaries
    assert "quiet refactor" in summaries


def _release_sections(markdown: str) -> dict[str, str]:
    body = markdown.split("## Update log", 1)[1]
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            if current is not None:
                sections[current] = "\n".join(buf)
            current, buf = line[4:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf)
    return sections


def test_release_grouping_before_and_after_a_tag(world: FeaturesWorld) -> None:
    early = world.clone("early")
    world.branch(early, "feat/6-early")
    proc = world.features_py(early, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "early change", "--pr", "6", "--date", "2026-01-08")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(early, "early change entry")
    world.push(early, "feat/6-early")
    world.merge("feat/6-early")
    world.tag("v1.0.0")

    late = world.clone("late")
    world.branch(late, "feat/7-late")
    proc = world.features_py(late, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "late change", "--pr", "7", "--date", "2026-01-09")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(late, "late change entry")
    world.push(late, "feat/7-late")
    world.merge("feat/7-late")

    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    md = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    sections = _release_sections(md)
    assert "early change" in sections["v1.0.0"]
    assert "late change" not in sections["v1.0.0"]
    assert "late change" in sections["Unreleased"]
    assert "early change" not in sections["Unreleased"]


def test_release_grouping_uses_pending_version_before_the_tag_lands(world: FeaturesWorld) -> None:
    early = world.clone("early")
    world.branch(early, "feat/6-early")
    proc = world.features_py(early, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "early change", "--pr", "6", "--date", "2026-01-08")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(early, "early change entry")
    world.push(early, "feat/6-early")
    world.merge("feat/6-early")
    world.tag("v1.0.0")

    late = world.clone("late")
    world.branch(late, "feat/7-late")
    proc = world.features_py(late, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "late change", "--pr", "7", "--date", "2026-01-09")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(late, "late change entry")
    world.push(late, "feat/7-late")
    world.merge("feat/7-late")

    bump = world.clone("bump")
    world.branch(bump, "release/bump-1.1.0")
    (bump / "macOS").mkdir(parents=True, exist_ok=True)
    (bump / "macOS" / "package.json").write_text(
        json.dumps({"name": "cloude-code-menubar", "version": "1.1.0"}), encoding="utf-8",
    )
    world.commit_all(bump, "release: bump macOS/package.json to 1.1.0")
    world.push(bump, "release/bump-1.1.0")
    world.merge("release/bump-1.1.0")

    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    md = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    sections = _release_sections(md)
    assert "late change" in sections["v1.1.0"], sections
    assert "Unreleased" not in sections or "late change" not in sections["Unreleased"]
    assert "early change" in sections["v1.0.0"]

    world.tag("v1.1.0")
    rendered_again = world.features_py(world.hub, "render")
    assert rendered_again.returncode == 0, rendered_again.stdout + rendered_again.stderr
    md_again = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    sections_again = _release_sections(md_again)
    assert "late change" in sections_again["v1.1.0"]


def test_release_field_override_pins_a_backfilled_entry(world: FeaturesWorld) -> None:
    early = world.clone("early")
    world.branch(early, "feat/6-early")
    proc = world.features_py(early, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "early change", "--pr", "6", "--date", "2026-01-08")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(early, "early change entry")
    world.push(early, "feat/6-early")
    world.merge("feat/6-early")
    world.tag("v1.0.0")

    backfill = world.clone("backfill")
    world.branch(backfill, "feat/9-backfill")
    proc = world.features_py(backfill, "new-change", "--type", "fixed", "--features", "thing",
                              "--summary", "backfilled fix for an old release", "--pr", "9",
                              "--date", "2026-01-20")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    entry_path = backfill / "features" / "changes" / "2026-01-20-9-backfilled-fix-for-an-old-release.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["release"] = "v1.0.0"
    _write(entry_path, entry)
    world.commit_all(backfill, "backfill entry, pinned to v1.0.0")
    world.push(backfill, "feat/9-backfill")
    world.merge("feat/9-backfill")

    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    md = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    sections = _release_sections(md)
    assert "backfilled fix for an old release" in sections["v1.0.0"], sections
    assert "Unreleased" not in sections or "backfilled fix for an old release" not in sections["Unreleased"]

    index = json.loads((world.hub / "features" / "index.json").read_text(encoding="utf-8"))
    backfilled = next(c for c in index["changes"] if c["summary"] == "backfilled fix for an old release")
    assert backfilled["release"] == "v1.0.0"


def test_render_is_deterministic(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/8-det")
    proc = world.features_py(worker, "new-change", "--type", "fixed", "--features", "thing",
                              "--summary", "determinism check", "--pr", "8", "--date", "2026-01-11")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(worker, "change entry")
    world.push(worker, "feat/8-det")
    world.merge("feat/8-det")

    first = world.features_py(world.hub, "render")
    assert first.returncode == 0, first.stdout + first.stderr
    snapshot = {
        name: (world.hub / name).read_text(encoding="utf-8")
        for name in ("FEATURES.md", "features/index.json", "features/schema.json")
    }
    second = world.features_py(world.hub, "render")
    assert second.returncode == 0, second.stdout + second.stderr
    for name, text in snapshot.items():
        assert (world.hub / name).read_text(encoding="utf-8") == text, name


def test_index_json_validates_against_schema_json(world: FeaturesWorld) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/9-schema")
    proc = world.features_py(worker, "new-change", "--type", "fixed", "--features", "thing",
                              "--summary", "schema check", "--pr", "9", "--date", "2026-01-12")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(worker, "change entry")
    world.push(worker, "feat/9-schema")
    world.merge("feat/9-schema")

    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    schema = json.loads((world.hub / "features" / "schema.json").read_text(encoding="utf-8"))
    index = json.loads((world.hub / "features" / "index.json").read_text(encoding="utf-8"))

    for area in index["areas"]:
        assert _schema_errors(area, schema["$defs"]["area"]) == []
    for entry in index["catalog"]:
        assert _schema_errors(entry, schema["$defs"]["catalogEntry"]) == []
    for change in index["changes"]:
        assert _schema_errors(change, schema["$defs"]["changeEntry"]) == []


def test_two_prs_each_with_a_change_file_merge_back_to_back(world: FeaturesWorld) -> None:
    a, b = world.clone("worker_a"), world.clone("worker_b")
    world.branch(a, "feat/10-a")
    proc = world.features_py(a, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "change a", "--pr", "10", "--date", "2026-01-13")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(a, "change a entry")
    world.push(a, "feat/10-a")

    world.branch(b, "feat/11-b")
    proc = world.features_py(b, "new-change", "--type", "added", "--features", "thing",
                              "--summary", "change b", "--pr", "11", "--date", "2026-01-13")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    world.commit_all(b, "change b entry")
    world.push(b, "feat/11-b")

    world.merge("feat/10-a")
    world.merge("feat/11-b")
    rendered = world.features_py(world.hub, "render")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    md = (world.hub / "FEATURES.md").read_text(encoding="utf-8")
    assert "change a" in md and "change b" in md



_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000000000200015e2c9b6b0000000049454e44ae426082"
)
SHOWN = {
    "where": ["open the drawer"], "how_to": ["click the thing"], "examples": ["when you need it"],
    "media": [{"kind": "screenshot", "file": "main.png", "caption": "the thing", "alt": "the thing, open"}],
}
SPEC = {"feature": "thing", "shots": [{"name": "main", "kind": "screenshot", "steps": [{"goto": "/"}]}]}


def _shown_repo(tmp_path: Path, entry: dict | None = None, spec: dict | None = None) -> Path:
    repo = _bare_repo(tmp_path)
    _write(repo / "features" / "areas.json", [BASE_AREA])
    _write(repo / "features" / "catalog" / "thing.json", entry or {**BASE_ENTRY, **SHOWN})
    (repo / "features" / "media" / "thing").mkdir(parents=True)
    (repo / "features" / "media" / "thing" / "main.png").write_bytes(_PNG)
    (repo / "features" / "capture").mkdir()
    _write(repo / "features" / "capture" / "thing.json", spec or SPEC)
    return repo


def test_media_positive_control_passes(tmp_path: Path) -> None:
    proc = _check(_shown_repo(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_media_missing_file_fails(tmp_path: Path) -> None:
    repo = _shown_repo(tmp_path)
    (repo / "features" / "media" / "thing" / "main.png").unlink()
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "does not exist" in proc.stderr
    assert "python3 scripts/feature_capture.py thing" in proc.stderr


def test_media_oversize_file_fails(tmp_path: Path) -> None:
    repo = _shown_repo(tmp_path)
    (repo / "features" / "media" / "thing" / "main.png").write_bytes(_PNG + b"\0" * (400 * 1024))
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "over the" in proc.stderr and "cap" in proc.stderr


def test_media_dotdot_path_fails(tmp_path: Path) -> None:
    entry = {**BASE_ENTRY, **SHOWN,
             "media": [{"kind": "screenshot", "file": "../other/main.png", "caption": "c", "alt": "a"}]}
    repo = _shown_repo(tmp_path, entry=entry)
    (repo / "features" / "media" / "other").mkdir()
    (repo / "features" / "media" / "other" / "main.png").write_bytes(_PNG)
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "../other/main.png" in proc.stderr
    assert "no '..' or '/'" in proc.stderr


def test_media_missing_alt_fails(tmp_path: Path) -> None:
    for item in ({"kind": "screenshot", "file": "main.png", "caption": "c"},
                 {"kind": "screenshot", "file": "main.png", "caption": "c", "alt": "   "}):
        repo = _shown_repo(tmp_path / str(len(item)) / ("blank" if "alt" in item else "absent"),
                           entry={**BASE_ENTRY, **SHOWN, "media": [item]})
        proc = _check(repo)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "alt" in proc.stderr


def test_media_not_produced_by_capture_spec_fails(tmp_path: Path) -> None:
    spec = {"feature": "thing", "shots": [{"name": "other", "kind": "screenshot", "steps": []}]}
    proc = _check(_shown_repo(tmp_path, spec=spec))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "not produced by any shot" in proc.stderr


def test_media_stray_file_fails(tmp_path: Path) -> None:
    repo = _shown_repo(tmp_path)
    (repo / "features" / "media" / "thing" / "leftover.png").write_bytes(_PNG)
    proc = _check(repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "leftover.png" in proc.stderr and "not listed" in proc.stderr


def test_capture_spec_unknown_step_fails(tmp_path: Path) -> None:
    spec = {"feature": "thing", "shots": [{"name": "main", "kind": "screenshot", "steps": [{"teleport": "/"}]}]}
    proc = _check(_shown_repo(tmp_path, spec=spec))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "unknown step 'teleport'" in proc.stderr


def _branch_with(world: FeaturesWorld, entry: dict, change: dict, *, touch_surface: bool,
                 recapture: bool) -> subprocess.CompletedProcess:
    worker = world.clone("worker")
    world.branch(worker, "feat/20-show")
    _write(worker / "features" / "catalog" / "thing.json", {**entry, "updated": "2026-02-01"})
    if entry.get("media"):
        (worker / "features" / "media" / "thing").mkdir(parents=True, exist_ok=True)
        (worker / "features" / "media" / "thing" / "main.png").write_bytes(_PNG)
        (worker / "features" / "capture").mkdir(exist_ok=True)
        _write(worker / "features" / "capture" / "thing.json", SPEC)
    world.commit_all(worker, "catalog on the branch")
    if touch_surface:
        (worker / "src" / "app.py").write_text("x = 99\n", encoding="utf-8")
    if recapture:
        (worker / "features" / "media" / "thing" / "main.png").write_bytes(_PNG + b"\0")
    (worker / "features" / "changes").mkdir(exist_ok=True)
    _write(worker / "features" / "changes" / "2026-02-01-20-show.json", change)
    world.commit_all(worker, "the change")
    return world.features_py(worker, "check", "--branch")


def _seed_shown_master(world: FeaturesWorld, entry: dict) -> None:
    seeder = world.clone("seeder")
    world.branch(seeder, "feat/19-seed")
    _write(seeder / "features" / "catalog" / "thing.json", entry)
    (seeder / "features" / "media" / "thing").mkdir(parents=True)
    (seeder / "features" / "media" / "thing" / "main.png").write_bytes(_PNG)
    (seeder / "features" / "capture").mkdir()
    _write(seeder / "features" / "capture" / "thing.json", SPEC)
    world.commit_all(seeder, "seed a shown feature")
    world.push(seeder, "feat/19-seed")
    world.merge("feat/19-seed")


ADDED = {"date": "2026-02-01", "type": "added", "features": ["thing"], "summary": "s", "pr": 20}


def test_branch_added_feature_with_no_media_and_no_exemption_fails(world: FeaturesWorld) -> None:
    refused = _branch_with(world, BASE_ENTRY, ADDED, touch_surface=False, recapture=False)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    for field in ("where", "how_to", "examples", "media"):
        assert field in refused.stderr
    assert "python3 scripts/feature_capture.py thing" in refused.stderr


def test_branch_fixed_entry_never_requires_media(world: FeaturesWorld) -> None:
    passed = _branch_with(world, BASE_ENTRY, {**ADDED, "type": "fixed"}, touch_surface=False, recapture=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_media_exempt_is_honored(world: FeaturesWorld) -> None:
    entry = {**BASE_ENTRY, **{k: v for k, v in SHOWN.items() if k != "media"},
             "media_exempt": "API only, nothing to see"}
    passed = _branch_with(world, entry, ADDED, touch_surface=False, recapture=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_fully_shown_added_feature_passes(world: FeaturesWorld) -> None:
    passed = _branch_with(world, {**BASE_ENTRY, **SHOWN}, ADDED, touch_surface=False, recapture=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_surface_change_without_recapture_fails(world: FeaturesWorld) -> None:
    shown = {**BASE_ENTRY, **SHOWN, "surfaces": ["src/app.py"]}
    _seed_shown_master(world, shown)
    changed = {**ADDED, "type": "changed"}
    refused = _branch_with(world, shown, changed, touch_surface=True, recapture=False)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "src/app.py" in refused.stderr and "Recapture" in refused.stderr
    assert "python3 scripts/feature_capture.py thing" in refused.stderr


def test_branch_surface_change_with_recapture_passes(world: FeaturesWorld) -> None:
    shown = {**BASE_ENTRY, **SHOWN, "surfaces": ["src/app.py"]}
    _seed_shown_master(world, shown)
    passed = _branch_with(world, shown, {**ADDED, "type": "changed"}, touch_surface=True, recapture=True)
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_surface_change_with_media_unchanged_passes(world: FeaturesWorld) -> None:
    shown = {**BASE_ENTRY, **SHOWN, "surfaces": ["src/app.py"]}
    _seed_shown_master(world, shown)
    change = {**ADDED, "type": "changed", "media_unchanged": True}
    passed = _branch_with(world, shown, change, touch_surface=True, recapture=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr
