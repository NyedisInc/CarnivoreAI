
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

from scripts.maintenance import huddle_rename_rules as rules
from tests.python.maintenance.test_rename_plugin_folders import commit, read, run_git, write_tree

TREE: Dict[str, str] = {
    "src/plugins/order.json": '{"order": ["huddle", "flow"]}\n',
    "src/plugins/huddle/cplug.json": (
        '{\n  "schema": 1,\n  "id": "huddle",\n  "name_key": "cplug.huddle.name",\n'
        '  "surfaces": { "topics": ["list", "delta"], "widgets": ["chat"], "tabs": ["huddle"] },\n'
        '  "owns": { "tests": ["tests/python/cplugs/huddle/"], "style_guide": ["web/src/cplugs/huddle/A.svelte"] },\n'
        '  "widgets": {\n    "chat": {\n      "instancing": "per-target"\n    }\n  }\n}\n'
    ),
    "src/plugins/huddle/__init__.py": "",
    "src/plugins/huddle/routes_common.py": (
        "from src.plugins.huddle import store\n"
        'router = cplug_router("huddle")\n'
        'FILE_URL = "/api/v1" + router_prefix("huddle") + "/items"\n'
        'DB = state / "cplugs" / "huddle" / "huddle.db"\n'
        'TOPIC = "cplug.huddle.delta"\n'
        'KEY = "cplug.huddle.list.title"\n'
        'TOOL = "task_manager_add"\n'
    ),
    "src/plugins/huddle/store.py": "x = 1\n",
    "src/plugins/flow/cplug.json": '{\n  "id": "flow",\n  "requires": ["huddle"]\n}\n',
    "src/api/span.py": 'tm = runtime.find("huddle")\nPACK = manifest["huddle"]\n',
    "web/src/plugins/huddle/index.ts": "import manifest from '../../../../src/plugins/huddle/cplug.json';\nexport const huddleCplug = { id: 'huddle' };\n",
    "web/src/plugins/huddle/chat/index.ts": "export const chatWidget = { name: 'chat' };\n",
    "web/src/plugins/huddle/huddle-model.ts": "export const TOPICS = ['cplug.huddle.list', 'cplug.huddle.list.agent'];\n",
    "web/src/lib/x.ts": (
        "import { huddleCplug } from '../plugins/huddle/index';\n"
        "import m from '../plugins/huddle/huddle-model';\n"
        "const kind = 'huddle.chat:row:1';\n"
        "const url = '/api/v1/cplugs/huddle/lists';\n"
    ),
    "web/src/plugins/flow/a.ts": "import { y } from '../huddle/huddle-model';\nimport z from '../huddle-model';\n",
    "tests/python/cplugs/huddle/test_a.py": "from tests.python.cplugs.huddle.helpers import h\nfrom src.plugins import huddle\n",
    "tests/python/cplugs/huddle/helpers.py": "h = 1\n",
    "scripts/gate/tree_copy.py": 'NOT_REMOVABLE: Dict[str, str] = {\n    "huddle": "the Task Manager",\n}\nOTHER = {\n    "huddle": 1,\n}\n',
    "docs/guide.md": "See `src/plugins/huddle/store.py`; data stays in `<state>/cplugs/huddle/huddle.db`.\n",
    "docs/DECISIONS.md": "2026-11-22: the code is in src/plugins/huddle.\n",
}


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q")
    write_tree(path, TREE)
    commit(path, "before")
    return path


def run(repo: Path, *flags: str) -> int:
    from scripts.maintenance import rename_plugin_folders as tool

    return tool.main(["--root", str(repo), "--rules", "huddle", *flags])


def test_check_is_red_before_and_green_after(repo: Path) -> None:
    assert run(repo, "--check") == 1
    assert run(repo) == 0
    assert run(repo, "--check") == 0
    staged = run_git(repo, "diff", "--cached", "--name-only")
    assert run(repo) == 0 and run_git(repo, "diff", "--cached", "--name-only") == staged


def test_moves_folders_and_rewrites_code_paths_and_ids(repo: Path) -> None:
    assert run(repo) == 0
    assert not (repo / "src/plugins/huddle").exists() and (repo / "src/plugins/taskmanager/store.py").is_file()
    assert (repo / "tests/python/cplugs/taskmanager/helpers.py").is_file()
    common = read(repo, "src/plugins/taskmanager/routes_common.py")
    assert "from src.plugins.taskmanager import store" in common and 'cplug_router("taskmanager")' in common
    assert 'TOPIC = "cplug.taskmanager.delta"' in common
    manifest = read(repo, "src/plugins/taskmanager/cplug.json")
    assert '"id": "taskmanager",\n  "renamed_from": "huddle",\n  "renamed_from_keeps": ["strings", "widgets"],' in manifest
    assert '"widgets": ["huddle.chat"]' in manifest and '"huddle.chat": {' in manifest
    assert "tests/python/cplugs/taskmanager/" in manifest and "web/src/cplugs/taskmanager/A.svelte" in manifest
    assert read(repo, "src/plugins/flow/cplug.json").count('"requires": ["taskmanager"]') == 1
    assert read(repo, "src/plugins/order.json") == '{"order": ["taskmanager", "flow"]}\n'
    assert 'runtime.find("taskmanager")' in read(repo, "src/api/span.py")
    web = read(repo, "web/src/lib/x.ts")
    assert "import { taskmanagerCplug } from '../plugins/taskmanager/index';" in web and "'../plugins/taskmanager/huddle-model'" in web
    assert "'../../../../src/plugins/taskmanager/cplug.json'" in read(repo, "web/src/plugins/taskmanager/index.ts")
    assert "id: 'taskmanager'" in read(repo, "web/src/plugins/taskmanager/index.ts")
    assert "name: 'huddle.chat'" in read(repo, "web/src/plugins/taskmanager/chat/index.ts")
    flow = read(repo, "web/src/plugins/flow/a.ts")
    assert "'../taskmanager/huddle-model'" in flow and "'../huddle-model'" in flow
    assert "from src.plugins import taskmanager as huddle" in read(repo, "tests/python/cplugs/taskmanager/test_a.py")
    assert "`src/plugins/taskmanager/store.py`" in read(repo, "docs/guide.md")
    gate = read(repo, "scripts/gate/tree_copy.py")
    assert '{\n    "taskmanager": "the Task Manager",\n}' in gate and 'OTHER = {\n    "huddle": 1,' in gate


def test_kept_names_stay(repo: Path) -> None:
    assert run(repo) == 0
    common = read(repo, "src/plugins/taskmanager/routes_common.py")
    for kept in ('router_prefix("huddle")', '"cplugs" / "huddle" / "huddle.db"', '"cplug.huddle.list.title"', '"task_manager_add"'):
        assert kept in common
    assert "'cplug.huddle.list.agent'" in read(repo, "web/src/plugins/taskmanager/huddle-model.ts")
    assert "'huddle.chat:row:1'" in read(repo, "web/src/lib/x.ts") and "/api/v1/cplugs/huddle/lists" in read(repo, "web/src/lib/x.ts")
    assert 'manifest["huddle"]' in read(repo, "src/api/span.py")
    assert '"tabs": ["huddle"]' in read(repo, "src/plugins/taskmanager/cplug.json")
    assert "`<state>/cplugs/huddle/huddle.db`" in read(repo, "docs/guide.md")
    assert read(repo, "docs/DECISIONS.md") == TREE["docs/DECISIONS.md"]


def test_a_rule_that_eats_a_kept_name_writes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = rules.TextRule("bad", re.compile(r"huddle\.db"), "taskmanager.db")
    monkeypatch.setattr(rules, "TEXT_RULES", rules.TEXT_RULES + (bad,))
    assert run(repo) == 1
    assert (repo / "src/plugins/huddle/store.py").is_file() and run_git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize(("spec", "importer", "expected"), [
    ("../../plugins/huddle/a", "web/src/lib/x", "../../plugins/taskmanager/a"),
    ("./huddle/style-guide/specimens", "web/src/plugins", "./taskmanager/style-guide/specimens"),
    ("../huddle-model", "web/src/plugins/huddle/chat", None),
    ("./lib/huddle-agent/screen-host", "web/src", None),
    ("../index", "web/src/plugins/huddle/chat", None),
])
def test_specifier_resolution(spec: str, importer: str, expected: object) -> None:
    assert rules.rewrite_specifier(spec, importer) == expected


def test_every_registered_rule_set_carries_every_protocol_member() -> None:
    from scripts.maintenance import rename_plugin_folders as tool

    members = ["FOLDER_MOVES", *(n for n, v in vars(tool.RuleSet).items() if callable(v) and not n.startswith("_"))]
    assert len(members) > 3, "the Protocol's methods were not found, so the check would look at nothing"
    for name, rule_set in tool.RULE_SETS.items():
        missing = [n for n in members if not hasattr(rule_set, n)]
        assert missing == [], f"rule set {name} lacks {missing}"
