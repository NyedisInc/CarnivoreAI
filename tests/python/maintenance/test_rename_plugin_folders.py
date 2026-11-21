
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from scripts.maintenance import plugin_rename_rules as rules
from scripts.maintenance import rename_plugin_folders as tool

REPO = Path(__file__).resolve().parents[3]
FIELD_INSTALLS = (REPO / "scripts" / "gate" / "field_installs.py").read_text(encoding="utf-8")

MANIFEST = '{"id": "alpha", "owns": {"tests": ["web/src/cplugs/alpha/"], "style_guide": ["web/src/cplugs/alpha/A.svelte"]}}\n'

TREE: Dict[str, str] = {
    "src/cplugs/__init__.py": '"""loader"""\n',
    "src/cplugs/order.json": '["alpha"]\n',
    "src/cplugs/alpha/cplug.json": MANIFEST,
    "src/cplugs/alpha/__init__.py": (
        "from src.cplugs.sdk import thing\n"
        "ROOT = Path('src') / 'cplugs' / 'alpha'\n"
        "ROUTE = '/api/v1/cplugs/alpha'\n"
        "STATE = Path(state) / 'cplugs' / 'alpha'\n"
        "# see src/cplugs/host/runtime.py and tests/python/cplugs/test_a.py\n"
    ),
    "src/cplugs/sdk/__init__.py": "thing = 1\n",
    "src/cplugs/sdk/ownership.py": (
        '"""contributions live under ``src/cplugs/<id>/`` and ``web/src/cplugs/<id>/`` (tests under\n'
        "``tests/python/cplugs/<id>/``)\n"
        "paths relative to ``web/src/cplugs/<id>/``; ``style_guide`` are paths under ``web/src/cplugs/<id>/``;\n"
        '"""\n'
        '    web_root, py_tests = f"web/src/cplugs/{cplug_id}/", f"tests/python/cplugs/{cplug_id}/"\n'
        "# the plugin folder is src/cplugs/<id>\n"
    ),
    "docs/cplugs.md": (
        "| Server code | `src/cplugs/<id>/`, `web/src/cplugs/<id>/` | `surfaces` |\n"
        "| Tests | `tests/python/cplugs/<id>/`, or beside the web files in `web/src/cplugs/<id>/` | `owns.tests` |\n"
        "| Style guide entries | specimens under `web/src/cplugs/<id>/` | `owns.style_guide` |\n"
        "| Contributions | the plugin | `owns.contributions` |\n"
        "\n"
        "**Core reaches a plugin only through the seams:** the registry (`src/cplugs/registry.py`).\n"
    ),
    "design/boards/b1/r001.html": "<p>a frozen review board mentions src/cplugs/host/a.py</p>\n",
    "design/boards/README.md": "Scan with `python3 -m src.cplugs.reviewboard.cli.scan design/boards`.\n",
    "scripts/gate/field_installs.py": FIELD_INSTALLS,
    "web/src/cplugs/alpha/A.svelte": "import x from '../../lib/x';\nimport y from '../../cplugs/sdk/y';\nimport z from './B.svelte';\n",
    "web/src/cplugs/alpha/B.svelte": "<script></script>\n",
    "web/src/cplugs/sdk/y.ts": "export const y = 1;\n",
    "web/src/lib/z.ts": (
        "import { a } from '../cplugs/alpha/A.svelte';\n"
        "import q from '../other/cplugs-thing';\n"
        "const topic = 'cplugs';\n"
    ),
    "src/cplugs/alpha/doc.py": (
        '"""Reads ``cplugs/sdk/thing.py`` and keeps data in <state>/cplugs/alpha/huddle.db and cplugs/state.json."""\n'
    ),
    "web/src/lib/frag.ts": (
        "const id = /cplugs\\/([^/]+)\\//.exec(path)?.[1];\n"
        "const row = /^\\/cplugs\\/([^/]+)\\/activity$/.exec(url);\n"
    ),
    "web/src/lib/q.test.ts": (
        "const KNOWN = ['cplugs/alpha/A.svelte x1', 'cplugs/sdk/y.ts|transparent'];\n"
        "// the state folder is `cplugs/<id>`, not code\n"
    ),
    "tests/python/cplugs/test_cplug_ownership.py": "    missing += [t for t in (*owns.tests, *owns.style_guide) if not (ROOT / t).exists()]\n",
    "scripts/plugin/check.py": 'shipped = [p.parent.name for p in (SCHEMA_DIR.parents[1] / "cplugs").glob("*/cplug.json")]\n',
    "web/scripts/build.mjs": "const root = join(webDir, 'src', 'cplugs');\n",
    "docs/guide.md": "Plugins live in `src/cplugs/<id>` and `web/src/cplugs/<id>`; state is `<state>/cplugs/<id>`.\n",
    "docs/DECISIONS.md": "2026-01-01: the code is in src/cplugs and `from src.cplugs import x`.\n",
    "docs/rename-carnivore.md": "register: src/cplugs\n",
    "docs/old-archive-import.md": "Code: `src/cplugs/save/x.py`.\n",
    "docs/claude-md-archive-2026-09-13.md": "the old text named src/cplugs\n",
    "client/dist/app.js": "/* built */ import('web/src/cplugs/alpha/A.svelte');\n",
    "tests/python/cplugs/test_a.py": "from src.cplugs.alpha import thing\nHERE = 'tests/python/cplugs/'\n",
}


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def write_tree(repo: Path, tree: Dict[str, str]) -> None:
    for rel, text in tree.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run_git(repo, "add", "--", *tree)


def commit(repo: Path, message: str) -> None:
    run_git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q")
    write_tree(path, TREE)
    commit(path, "old layout")
    return path


def run(repo: Path, *flags: str) -> int:
    return tool.main(["--root", str(repo), *flags])


def read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


def test_check_is_red_before_and_green_after(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "--check") == tool.EXIT_REFUSED
    out = capsys.readouterr().out
    assert "src/cplugs/alpha/__init__.py: still inside the old folder" in out
    assert "web/src/lib/z.ts: line 1: relative import specifier" in out
    assert run(repo) == tool.EXIT_OK
    assert run(repo, "--check") == tool.EXIT_OK


def test_moves_and_rewrites_code_paths(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    files = run_git(repo, "ls-files").split()
    assert "src/plugins/alpha/__init__.py" in files and "web/src/plugins/alpha/A.svelte" in files
    assert not [f for f in files if f.startswith(("src/cplugs/", "web/src/cplugs/"))]
    assert not (repo / "src" / "cplugs").exists() and not (repo / "web" / "src" / "cplugs").exists()
    init = read(repo, "src/plugins/alpha/__init__.py")
    assert "from src.plugins.sdk import thing" in init
    assert "Path('src') / 'plugins' / 'alpha'" in init
    assert "src/plugins/host/runtime.py" in init
    assert "import y from '../../plugins/sdk/y';" in read(repo, "web/src/plugins/alpha/A.svelte")
    assert "import x from '../../lib/x';" in read(repo, "web/src/plugins/alpha/A.svelte")
    assert "from '../plugins/alpha/A.svelte'" in read(repo, "web/src/lib/z.ts")
    assert "join(webDir, 'src', 'plugins')" in read(repo, "web/scripts/build.mjs")
    assert "`src/plugins/<id>` and `web/src/plugins/<id>`" in read(repo, "docs/guide.md")
    assert "``plugins/sdk/thing.py``" in read(repo, "src/plugins/alpha/doc.py")
    assert "<state>/cplugs/alpha/huddle.db and cplugs/state.json" in read(repo, "src/plugins/alpha/doc.py")
    assert "['plugins/alpha/A.svelte x1', 'plugins/sdk/y.ts|transparent']" in read(repo, "web/src/lib/q.test.ts")
    assert "`cplugs/<id>`" in read(repo, "web/src/lib/q.test.ts")
    owns_test = read(repo, "tests/python/cplugs/test_cplug_ownership.py")
    assert 't.replace("web/src/cplugs/", "web/src/plugins/", 1)' in owns_test
    assert run(repo, "--check") == tool.EXIT_OK
    assert '(SCHEMA_DIR.parents[1] / "plugins")' in read(repo, "scripts/plugin/check.py")
    assert "from src.plugins.alpha import thing" in read(repo, "tests/python/cplugs/test_a.py")


def test_stored_names_and_history_stay(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    init = read(repo, "src/plugins/alpha/__init__.py")
    assert "'/api/v1/cplugs/alpha'" in init and "Path(state) / 'cplugs' / 'alpha'" in init
    assert "tests/python/cplugs/test_a.py" in init
    assert read(repo, "src/plugins/alpha/cplug.json") == MANIFEST
    assert read(repo, "src/plugins/order.json") == TREE["src/cplugs/order.json"]
    own = read(repo, "src/plugins/sdk/ownership.py")
    assert 'web_root, py_tests = f"web/src/cplugs/{cplug_id}/", f"tests/python/cplugs/{cplug_id}/"' in own
    assert "src/plugins/<id>" in own
    assert "const topic = 'cplugs';" in read(repo, "web/src/lib/z.ts")
    assert "'../other/cplugs-thing'" in read(repo, "web/src/lib/z.ts")
    assert "HERE = 'tests/python/cplugs/'" in read(repo, "tests/python/cplugs/test_a.py")
    assert read(repo, "docs/old-archive-import.md") == "Code: `src/plugins/save/x.py`.\n"
    for rel in ("docs/DECISIONS.md", "docs/rename-carnivore.md", "client/dist/app.js", "docs/claude-md-archive-2026-09-13.md"):
        assert read(repo, rel) == TREE[rel]
    assert "<state>/cplugs/<id>" in read(repo, "docs/guide.md")


def test_dry_run_writes_nothing_and_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = run_git(repo, "status", "--porcelain"), read(repo, "docs/guide.md")
    assert run(repo, "--dry-run") == tool.EXIT_OK
    out = capsys.readouterr().out
    assert "would move folder src/cplugs -> src/plugins" in out
    assert "rule dotted module path:" in out and "rule slash path:" in out and "rule relative import specifier: 2" in out
    assert "folder web:" in out and "folder src:" in out
    assert (run_git(repo, "status", "--porcelain"), read(repo, "docs/guide.md")) == before
    assert (repo / "src" / "cplugs").is_dir()


def test_second_run_changes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo) == tool.EXIT_OK
    snapshot = (run_git(repo, "status", "--porcelain"), run_git(repo, "diff", "--cached"), run_git(repo, "diff"))
    capsys.readouterr()
    assert run(repo) == tool.EXIT_OK
    assert "nothing to do" in capsys.readouterr().out
    assert (run_git(repo, "status", "--porcelain"), run_git(repo, "diff", "--cached"), run_git(repo, "diff")) == snapshot


def test_rewrites_are_staged_and_nothing_is_committed(repo: Path) -> None:
    head = run_git(repo, "rev-parse", "HEAD")
    assert run(repo) == tool.EXIT_OK
    assert run_git(repo, "rev-parse", "HEAD") == head
    assert run_git(repo, "diff").strip() == ""
    assert "src/plugins/alpha/__init__.py" in run_git(repo, "diff", "--cached", "--name-only")


def test_refuses_a_dirty_tree(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "docs" / "guide.md").write_text("edited\n", encoding="utf-8")
    assert run(repo) == tool.EXIT_REFUSED
    assert "dirty tree" in capsys.readouterr().err
    assert (repo / "src" / "cplugs").is_dir() and not (repo / "src" / "plugins").exists()


def test_a_rule_that_eats_a_stored_name_writes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import re

    bad = rules.TextRule("bad rule", re.compile(r"api/v1/cplugs"), "api/v1/plugins")
    monkeypatch.setattr(rules, "TEXT_RULES", (*rules.TEXT_RULES, bad))
    assert run(repo) == tool.EXIT_REFUSED
    assert "stored or field-visible name" in capsys.readouterr().err
    assert (repo / "src" / "cplugs").is_dir()


def test_merge_fixup_moves_stragglers_and_rewrites_their_imports(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    commit(repo, "rename")
    write_tree(repo, {
        "src/cplugs/alpha/late.py": "from src.cplugs.sdk import thing\n",
        "web/src/cplugs/alpha/Late.svelte": "import y from '../../cplugs/sdk/y';\nimport w from '../../lib/w';\n",
    })
    commit(repo, "a branch merged in a late file under the old folders")
    assert run(repo, "--check") == tool.EXIT_REFUSED
    assert run(repo, "--fixup") == tool.EXIT_OK
    assert read(repo, "src/plugins/alpha/late.py") == "from src.plugins.sdk import thing\n"
    assert read(repo, "web/src/plugins/alpha/Late.svelte") == "import y from '../../plugins/sdk/y';\nimport w from '../../lib/w';\n"
    assert not (repo / "src" / "cplugs").exists()
    assert run(repo, "--check") == tool.EXIT_OK


def test_fixup_refuses_to_overwrite_a_file(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo) == tool.EXIT_OK
    commit(repo, "rename")
    write_tree(repo, {"src/cplugs/alpha/__init__.py": "different\n"})
    commit(repo, "a late file with the same name")
    assert run(repo, "--fixup") == tool.EXIT_REFUSED
    assert "destination exists" in capsys.readouterr().err
    assert (repo / "src" / "cplugs" / "alpha" / "__init__.py").is_file()


def test_fixup_needs_the_new_folders(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(repo, "--fixup") == tool.EXIT_REFUSED
    assert "new folders to exist" in capsys.readouterr().err


def test_not_a_git_repo_is_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert tool.main(["--root", str(tmp_path), "--check"]) == tool.EXIT_CANNOT


@pytest.mark.parametrize(
    "spec,importer,expected",
    [
        ("../../cplugs/huddle/a", "web/src/lib/x", "../../plugins/huddle/a"),
        ("../cplugs", "web/src/lib", "../plugins"),
        ("../../cplugs/sdk/y", "web/src/cplugs/alpha", "../../plugins/sdk/y"),
        ("../../lib/x", "web/src/cplugs/alpha", None),
        ("../other/cplugs-thing", "web/src/lib", None),
        ("../../state/cplugs/x", "web/src/lib/q", None),
        ("../../../cplugs/x", "web/src/lib/q", None),
    ],
)
def test_specifier_resolution(spec: str, importer: str, expected: object) -> None:
    assert rules.rewrite_specifier(spec, importer) == expected


def test_owns_contract_lines_keep_the_old_prefix(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    own = read(repo, "src/plugins/sdk/ownership.py")
    assert "``src/plugins/<id>/`` and ``web/src/cplugs/<id>/`` (tests under" in own
    assert "paths relative to ``web/src/cplugs/<id>/``; ``style_guide`` are paths under ``web/src/cplugs/<id>/``;" in own
    doc = read(repo, "docs/cplugs.md")
    assert "| `src/plugins/<id>/`, `web/src/plugins/<id>/` |" in doc
    assert "beside the web files in `web/src/cplugs/<id>/` | `owns.tests` |" in doc
    assert "specimens under `web/src/cplugs/<id>/` | `owns.style_guide` |" in doc
    assert "**Manifest `owns` values keep the `cplugs` prefix**" in doc
    assert doc.index("**Manifest `owns` values") < doc.index("**Core reaches a plugin")
    assert "(`src/plugins/registry.py`)" in doc
    assert run(repo, "--check") == tool.EXIT_OK
    again = read(repo, "docs/cplugs.md")
    assert run(repo) == tool.EXIT_OK and read(repo, "docs/cplugs.md") == again == doc


def test_review_board_snapshots_are_left_alone(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    assert read(repo, "design/boards/b1/r001.html") == TREE["design/boards/b1/r001.html"]
    assert "src.plugins.reviewboard.cli.scan" in read(repo, "design/boards/README.md")
    assert run(repo, "--check") == tool.EXIT_OK


def test_untracked_files_under_an_old_folder_stop_the_run(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "src" / "cplugs" / "alpha" / "scratch.py").write_text("from src.cplugs.sdk import thing\n", encoding="utf-8")
    assert run(repo) == tool.EXIT_REFUSED
    assert "untracked files under an old plugin folder" in capsys.readouterr().err
    assert (repo / "src" / "cplugs").is_dir() and not (repo / "src" / "plugins").exists()


def test_runs_only_as_a_module() -> None:
    ok = subprocess.run([sys.executable, "-m", "scripts.maintenance.rename_plugin_folders", "--help"], cwd=REPO, capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and "--fixup" in ok.stdout
    assert "sys.modules" not in (REPO / "scripts" / "maintenance" / "rename_plugin_folders.py").read_text(encoding="utf-8").split('"""', 2)[2]


def make_core(base: Path, layout: str) -> Path:
    files = {
        "macOS/package.json": '{"version": "1.16.2"}',
        "src/__init__.py": "",
        "src/core/__init__.py": "",
        "src/core/skills/__init__.py": "",
        "src/core/skills/stage.py": (
            "from types import SimpleNamespace\n"
            "def stage_archive(tarball, dest, publisher, name, kind):\n"
            "    dest.mkdir(parents=True)\n    (dest / 'carnivore.json').write_text('{\"min_app_version\": \"0\"}')\n"
            "    return SimpleNamespace(digest='d1')\n"
        ),
        f"src/{layout}/__init__.py": "",
        f"src/{layout}/host/__init__.py": "",
        f"src/{layout}/host/install_gates.py": "def evaluate(plugin_id, dest):\n    return None\n",
        f"src/{layout}/shipped/cplug.json": "{}",
    }
    core = base / f"core-{layout}"
    for rel, text in files.items():
        path = core / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return core


@pytest.mark.parametrize("layout", ["cplugs", "plugins"])
def test_field_installs_worker_probes_both_layouts(repo: Path, tmp_path: Path, layout: str) -> None:
    assert run(repo) == tool.EXIT_OK
    script = repo / "scripts" / "gate" / "field_installs.py"
    core = make_core(tmp_path, layout)
    jobs = [
        {"id": "shipped", "v": "1", "kind": "cplug", "name": "shipped", "publisher": "p"},
        {"id": "other", "v": "1", "kind": "cplug", "name": "other", "publisher": "p", "digest": "d1", "tarball": "t", "key_id": "k", "src_path": ""},
    ]
    spec = tmp_path / f"spec-{layout}.json"
    spec.write_text(json.dumps({"core": str(core), "jobs": jobs, "index": None, "upcoming": False}), encoding="utf-8")
    done = subprocess.run([sys.executable, "-I", str(script), "--worker", str(spec)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-400:]
    results = json.loads(done.stdout.strip().splitlines()[-1])
    assert [(r["id"], r["ok"], r["step"]) for r in results] == [("shipped", True, "builtin"), ("other", True, "ok")]


def test_regex_literal_over_a_code_path_is_rewritten_but_a_route_regex_is_not(repo: Path) -> None:
    assert run(repo) == tool.EXIT_OK
    text = read(repo, "web/src/lib/frag.ts")
    assert "/plugins\\/([^/]+)\\//.exec(path)" in text
    assert "/^\\/cplugs\\/([^/]+)\\/activity$/" in text
    assert run(repo, "--check") == tool.EXIT_OK
