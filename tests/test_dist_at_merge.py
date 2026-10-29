
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("web-build-check.sh", "dist-at-merge.sh", "admin-build-check.sh")
PY_SCRIPTS = ("features.py", "features_schema.py", "features_media.py")


def _expected_outputs() -> tuple[str, ...]:
    text = (REPO_ROOT / "scripts" / "web-build-check.sh").read_text()
    lines = [ln for ln in text.splitlines() if ln.startswith("EXPECTED_OUTPUTS=(")]
    assert len(lines) == 1, f"EXPECTED_OUTPUTS line not found once: {lines}"
    names = tuple(lines[0].split("(", 1)[1].rstrip(")").split())
    assert "app.js" in names and "app.css" in names, names
    return names


OUTPUTS = _expected_outputs()
PLACEHOLDERS = tuple(n for n in OUTPUTS if n != "app.js")

FAKE_NPM = r"""#!/usr/bin/env bash
# Stub npm: `npm ci` is a no-op, `npm run build` writes ../client/dist from
# the sorted web/src/*.txt. FAKE_NPM_FAIL makes the build fail.
# FAKE_NPM_RACE names a script run once, during the first build, to move
# master under the caller.
case "$1" in
  ci) mkdir -p node_modules; exit 0 ;;
  run)
    if [ "$2" = admin:build ]; then
      mkdir -p ../hosted/catalog/admin/dist
      { echo admin; cat $(ls src/*.txt | sort); } > ../hosted/catalog/admin/dist/admin.js
      exit 0
    fi
    [ "$2" = build ] || exit 1
    [ -n "${FAKE_NPM_FAIL:-}" ] && exit 1
    mkdir -p ../client/dist
    cat $(ls src/*.txt | sort) > ../client/dist/app.js
    for f in __PLACEHOLDERS__; do mkdir -p "$(dirname "../client/dist/$f")"; printf '%s\n' "$f" > "../client/dist/$f"; done
    if [ -n "${FAKE_NPM_RACE:-}" ] && [ ! -e "${FAKE_NPM_RACE}.done" ]; then
      touch "${FAKE_NPM_RACE}.done"
      bash "${FAKE_NPM_RACE}" >/dev/null 2>&1
    fi
    exit 0 ;;
esac
exit 1
""".replace("__PLACEHOLDERS__", " ".join(PLACEHOLDERS))


FAKE_GATE = r"""#!/usr/bin/env bash
root=""; while [ $# -gt 0 ]; do case "$1" in --root) root="$2"; shift 2 ;; *) echo "$1" >> "${HOME}/gate-args"; shift ;; esac; done
if [ -f "${root}/web/src/red.txt" ]; then
  echo "== TOP-DOWN GATE RED =="; echo "  vitest: src/lib/x/wrapper-rules.test.ts > has no copy outside KNOWN"; exit 1
fi
exit "${FAKE_GATE_RC:-0}"
"""


def _run(cwd: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


def _git(cwd: Path, env: dict, *args: str) -> str:
    proc = _run(cwd, env, "git", *args)
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


class World:

    def __init__(self, root: Path) -> None:
        self.root = root
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "npm").write_text(FAKE_NPM)
        (bin_dir / "node").write_text("#!/bin/sh\nexit 0\n")
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
        (root / "tmp").mkdir()
        (root / "gitconfig").write_text("")
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(root),
            "TMPDIR": str(root / "tmp"),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "CLOUDE_TRUNK_REMOTE": "origin",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.origin = root / "origin.git"
        _git(root, self.env, "init", "--quiet", "--bare", "-b", "master", str(self.origin))

        seed = root / "seed"
        _git(root, self.env, "init", "--quiet", "-b", "master", str(seed))
        (seed / "scripts").mkdir()
        shutil.copy2(REPO_ROOT / "scripts" / "__init__.py", seed / "scripts" / "__init__.py")
        for name in SCRIPTS + PY_SCRIPTS:
            shutil.copy2(REPO_ROOT / "scripts" / name, seed / "scripts" / name)
        shutil.copytree(
            REPO_ROOT / "scripts" / "lib", seed / "scripts" / "lib",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (seed / "scripts" / "design").mkdir()
        (seed / "scripts" / "design" / "check_top_down.sh").write_text(FAKE_GATE)
        (seed / "scripts" / "design" / "check_top_down.sh").chmod(0o755)
        (seed / "web" / "src").mkdir(parents=True)
        (seed / "web" / "src" / "base.txt").write_text("base\n")
        (seed / "web" / "vite.admin.config.ts").write_text("// stub\n")
        (seed / "hosted" / "catalog" / "admin" / "dist").mkdir(parents=True)
        (seed / "hosted" / "catalog" / "admin" / "dist" / "admin.js").write_text("admin\nbase\n")
        (seed / "client" / "dist").mkdir(parents=True)
        (seed / "client" / "dist" / "app.js").write_text("base\n")
        for name in PLACEHOLDERS:
            (seed / "client" / "dist" / name).parent.mkdir(parents=True, exist_ok=True)
            (seed / "client" / "dist" / name).write_text(f"{name}\n")
        (seed / "features" / "catalog").mkdir(parents=True)
        (seed / "features" / "changes").mkdir(parents=True)
        (seed / "features" / "areas.json").write_text(
            '[{"id": "core", "name": "Core", "blurb": "b"}]\n', encoding="utf-8"
        )
        (seed / "features" / "catalog" / "thing.json").write_text(
            json.dumps({
                "id": "thing", "name": "Thing", "summary": "s", "area": "core",
                "status": "stable", "since": "2026-01-01", "updated": "2026-01-01",
            }) + "\n",
            encoding="utf-8",
        )
        (seed / "FEATURES.md").write_text("# placeholder, stale\n", encoding="utf-8")
        (seed / "features" / "index.json").write_text('{"placeholder": true}\n', encoding="utf-8")
        (seed / "features" / "schema.json").write_text('{"placeholder": true}\n', encoding="utf-8")
        (seed / ".gitignore").write_text("node_modules/\n__pycache__/\n*.pyc\n")
        _git(seed, self.env, "add", ".")
        _git(seed, self.env, "commit", "--quiet", "-m", "seed")
        _git(seed, self.env, "remote", "add", "origin", str(self.origin))
        _git(seed, self.env, "push", "--quiet", "origin", "master")
        self.hub = self.clone("hub")

    def clone(self, name: str) -> Path:
        path = self.root / name
        _git(self.root, self.env, "clone", "--quiet", str(self.origin), str(path))
        return path

    def branch(self, clone: Path, branch: str, src: str, bundle: str | None = None) -> None:
        _git(clone, self.env, "checkout", "--quiet", "-b", branch)
        (clone / "web" / "src" / f"{src}.txt").write_text(f"{src}\n")
        paths = [f"web/src/{src}.txt"]
        if bundle is not None:
            (clone / "client" / "dist" / "app.js").write_text(bundle)
            paths.append("client/dist/app.js")
        _git(clone, self.env, "add", "--", *paths)
        _git(clone, self.env, "commit", "--quiet", "-m", f"add {src}")
        _git(clone, self.env, "push", "--quiet", "origin", branch)

    def merge(self, branch: str) -> None:
        _git(self.hub, self.env, "fetch", "--quiet", "origin")
        _git(self.hub, self.env, "checkout", "--quiet", "--force", "-B", "master", "origin/master")
        _git(self.hub, self.env, "merge", "--quiet", "--no-ff", "--no-edit", f"origin/{branch}")
        _git(self.hub, self.env, "push", "--quiet", "origin", "master")

    def master_file(self, path: str) -> str:
        return _git(self.root, self.env, "--git-dir", str(self.origin), "show", f"master:{path}") + "\n"

    def expected_bundle(self) -> str:
        names = _git(
            self.root, self.env, "--git-dir", str(self.origin),
            "ls-tree", "--name-only", "master", "web/src/",
        ).split("\n")
        return "".join(self.master_file(n) for n in sorted(names))

    def master_mode(self, *args: str) -> int:
        return self.master_mode_run(*args).returncode

    def master_mode_run(self, *args: str) -> subprocess.CompletedProcess:
        _git(self.hub, self.env, "fetch", "--quiet", "origin")
        _git(self.hub, self.env, "checkout", "--quiet", "--force", "--detach", "origin/master")
        proc = _run(self.hub, self.env, "scripts/web-build-check.sh", *args)
        _git(self.hub, self.env, "checkout", "--quiet", "--force", "--detach", "origin/master")
        return proc

    def dist_at_merge(self, clone: Path, **extra: str) -> subprocess.CompletedProcess:
        return _run(clone, {**self.env, **extra}, str(clone / "scripts" / "dist-at-merge.sh"))

    def commits(self) -> int:
        return int(_git(self.root, self.env, "--git-dir", str(self.origin), "rev-list", "--count", "master"))


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_branch_mode_refuses_a_committed_bundle_and_its_fix_works(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/1-x", "x", bundle="planted\n")
    refused = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "BUNDLE CHANGE ON A BRANCH" in refused.stderr
    assert "client/dist/app.js" in refused.stderr

    fix = [line.strip() for line in refused.stderr.splitlines() if line.strip().startswith("git ")]
    assert len(fix) == 2, refused.stderr
    for line in fix:
        assert _run(worker, world.env, "bash", "-c", line).returncode == 0, line
    passed = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_branch_mode_refuses_a_staged_bundle(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/2-y", "y")
    (worker / "client" / "dist" / "app.js").write_text("staged\n")
    _git(worker, world.env, "add", "--", "client/dist/app.js")
    proc = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "BUNDLE CHANGE ON A BRANCH" in proc.stderr


def test_branch_mode_passes_where_master_mode_demands_a_bundle(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/3-z", "z")
    branch = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert branch.returncode == 0, branch.stdout + branch.stderr
    assert "BRANCH BUILDS" in branch.stdout
    assert (worker / "client" / "dist" / "app.js").read_text() == "base\nz\n"

    strict = _run(worker, world.env, "scripts/web-build-check.sh")
    assert strict.returncode == 1, strict.stdout + strict.stderr
    assert "STALE BUNDLE" in strict.stderr
    assert "--branch" in strict.stderr


def test_branch_mode_cannot_evaluate_on_master_or_without_a_base(world: World) -> None:
    worker = world.clone("worker")
    on_master = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert on_master.returncode == 2, on_master.stderr
    world.branch(worker, "feat/4-w", "w")
    no_base = _run(
        worker, {**world.env, "CLOUDE_WEB_CHECK_BASE": "origin/nope"},
        "scripts/web-build-check.sh", "--branch",
    )
    assert no_base.returncode == 2, no_base.stderr
    assert "CANNOT EVALUATE" in no_base.stderr


def test_back_to_back_merges_each_leave_master_current(world: World) -> None:
    a, b = world.clone("worker_a"), world.clone("worker_b")
    world.branch(a, "feat/5-a", "a")
    world.branch(b, "feat/6-b", "b")

    for clone, branch in ((a, "feat/5-a"), (b, "feat/6-b")):
        world.merge(branch)
        assert world.master_mode() == 1, "the control: a merged branch leaves master stale"
        proc = world.dist_at_merge(clone)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "pushed rebuild" in proc.stdout
        assert world.master_file("client/dist/app.js") == world.expected_bundle()
        assert world.master_mode() == 0

    assert world.master_file("client/dist/app.js") == "a\nb\nbase\n"
    subject = _git(world.root, world.env, "--git-dir", str(world.origin), "log", "-1", "--format=%s", "master")
    assert subject == "rebuild generated files"

    before = world.commits()
    again = world.dist_at_merge(a)
    assert again.returncode == 0 and "already current" in again.stdout
    assert world.commits() == before, "a current master must not get a commit"

    assert _git(a, world.env, "worktree", "list").count("\n") == 0, "build worktree left behind"
    assert list((world.root / "tmp").iterdir()) == []


def test_in_flight_branch_bundle_is_overwritten(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/7-c", "c", bundle="stale from the branch\n")
    world.merge("feat/7-c")
    assert world.master_file("client/dist/app.js") == "stale from the branch\n"
    proc = world.dist_at_merge(worker)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert world.master_file("client/dist/app.js") == "base\nc\n"
    assert world.master_mode() == 0


def test_a_rejected_push_rebuilds_on_the_new_tip(world: World) -> None:
    worker, racer = world.clone("worker"), world.clone("racer")
    world.branch(worker, "feat/8-d", "d")
    world.merge("feat/8-d")
    race = world.root / "race.sh"
    race.write_text(
        f"cd '{racer}' && git pull --quiet origin master"
        " && printf 'r\\n' > web/src/r.txt && git add web/src/r.txt"
        " && git commit --quiet -m race && git push --quiet origin HEAD:master\n"
    )
    proc = world.dist_at_merge(worker, FAKE_NPM_RACE=str(race))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "push rejected" in proc.stderr
    assert "attempt 2/3" in proc.stdout
    assert world.master_file("client/dist/app.js") == "base\nd\nr\n"
    assert world.master_mode() == 0


def test_a_failed_build_is_cannot_evaluate_and_pushes_nothing(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/9-e", "e")
    world.merge("feat/9-e")
    before = world.commits()
    proc = world.dist_at_merge(worker, FAKE_NPM_FAIL="1")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert world.commits() == before


def test_stale_feature_catalog_is_rebuilt_alongside_dist_in_one_commit(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/10-f", "f")
    world.merge("feat/10-f")
    proc = world.dist_at_merge(worker)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "pushed rebuild" in proc.stdout

    subject = _git(world.root, world.env, "--git-dir", str(world.origin),
                    "log", "-1", "--format=%s", "master")
    assert subject == "rebuild generated files"
    touched = _git(world.root, world.env, "--git-dir", str(world.origin),
                    "show", "--stat", "--format=", "master")
    for path in ("client/dist/app.js", "FEATURES.md", "features/index.json", "features/schema.json"):
        assert path in touched, f"{path} missing from the merge-time commit:\n{touched}"

    md = world.master_file("FEATURES.md")
    assert "Thing" in md
    index = json.loads(world.master_file("features/index.json"))
    assert index["catalog"] and index["catalog"][0]["id"] == "thing"

    before = world.commits()
    again = world.dist_at_merge(worker)
    assert again.returncode == 0 and "already current" in again.stdout
    assert world.commits() == before


def test_branch_mode_refuses_a_hand_committed_features_md(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/11-g", "g")
    (worker / "FEATURES.md").write_text("hand-edited, not generated\n")
    _git(worker, world.env, "add", "FEATURES.md")
    _git(worker, world.env, "commit", "--quiet", "-m", "oops, committed FEATURES.md")
    refused = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "BUNDLE CHANGE ON A BRANCH" in refused.stderr
    assert "FEATURES.md" in refused.stderr

    fix = [line.strip() for line in refused.stderr.splitlines() if line.strip().startswith("git ")]
    assert len(fix) == 2, refused.stderr
    for line in fix:
        assert _run(worker, world.env, "bash", "-c", line).returncode == 0, line
    passed = _run(worker, world.env, "scripts/web-build-check.sh", "--branch")
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_stale_admin_bundle_is_rebuilt_in_the_same_commit(world: World) -> None:
    clone = world.clone("w1")
    world.branch(clone, "b1", "one")
    world.merge("b1")
    before = world.commits()
    proc = world.dist_at_merge(world.hub)
    assert proc.returncode == 0, proc.stderr
    assert world.commits() == before + 1
    assert world.master_file("hosted/catalog/admin/dist/admin.js") == "admin\n" + world.expected_bundle()
    assert world.dist_at_merge(world.hub).returncode == 0
    assert world.commits() == before + 1


def test_branch_mode_refuses_a_committed_admin_bundle(world: World) -> None:
    clone = world.clone("w2")
    world.branch(clone, "b2", "two")
    (clone / "hosted" / "catalog" / "admin" / "dist" / "admin.js").write_text("hand\n")
    _git(clone, world.env, "add", "--", "hosted/catalog/admin/dist/admin.js")
    proc = _run(clone, world.env, "scripts/web-build-check.sh", "--branch")
    assert proc.returncode == 1, proc.stderr
    assert "hosted/catalog/admin/dist/admin.js" in proc.stderr


def test_a_red_top_down_gate_refuses_the_rebuild_and_pushes_nothing(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/20-red", "red")
    world.merge("feat/20-red")
    before = world.commits()
    proc = world.dist_at_merge(worker)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REFUSED - master is red on the top-down scans" in proc.stderr
    assert "TOP-DOWN GATE RED" in proc.stdout + proc.stderr
    assert world.commits() == before
    assert _run(worker, world.env, "git", "rev-parse", "--verify", "--quiet", "refs/conformance/last-green").returncode != 0


def test_a_gate_that_could_not_run_is_cannot_evaluate(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/21-g", "g")
    world.merge("feat/21-g")
    before = world.commits()
    proc = world.dist_at_merge(worker, FAKE_GATE_RC="2")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert world.commits() == before


def test_a_green_gate_moves_last_green_and_the_next_range_starts_there(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/22-h", "h")
    world.merge("feat/22-h")
    tip = _git(world.root, world.env, "--git-dir", str(world.origin), "rev-parse", "master")
    proc = world.dist_at_merge(worker)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _git(worker, world.env, "rev-parse", "refs/conformance/last-green") == tip
    args = (world.root / "gate-args").read_text().split()
    assert "--ratchet-range" in args
    world.branch(worker, "feat/23-i", "i")
    world.merge("feat/23-i")
    assert world.dist_at_merge(worker).returncode == 0
    assert "refs/conformance/last-green..HEAD" in (world.root / "gate-args").read_text()


def test_refuse_mode_exits_3_on_a_red_gate_and_builds_nothing(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/24-r", "red")
    world.merge("feat/24-r")
    proc = world.master_mode_run("--gate=refuse")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "wrapper-rules.test.ts" in proc.stdout + proc.stderr
    assert "building web/" not in proc.stdout


def test_refuse_mode_never_passes_a_gate_that_could_not_run(world: World) -> None:
    world.env["FAKE_GATE_RC"] = "2"
    assert world.master_mode("--gate=refuse") == 2


def test_warn_mode_prints_the_findings_and_exits_as_the_build_check_would(world: World) -> None:
    worker = world.clone("worker")
    world.branch(worker, "feat/25-w", "red")
    world.merge("feat/25-w")
    proc = world.master_mode_run()
    out = proc.stdout + proc.stderr
    assert "wrapper-rules.test.ts" in out and "WARNING - the top-down gate is red" in out
    assert "building web/" in out
    assert proc.returncode in (0, 1), out
    assert proc.returncode != 3
