
from __future__ import annotations

import ast
import posixpath
import re
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[3]
PLATFORM_DIRS = {"sdk", "host", "runtime", "sdk_py"}
SEAMS = {"src/cplugs/registry.py", "web/src/cplugs/builtin.ts", "web/src/cplugs/popout.ts", "web/src/cplugs/early.ts", "web/src/cplugs/style-guide.ts"}
WEB_SUFFIXES = (".ts", ".svelte")
SPECIFIER = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*['"]([^'"\n]+)['"]""")
QUOTED_PLUGIN_PATH = re.compile(r"""['"]([^'"\n]*cplugs/[a-z0-9]+/[^'"\n]*)['"]""")

_TASK_MANAGER_UI = "huddle web UI imported by a screen outside the plugin folder; move the screen into the plugin or expose it through the sdk"

KNOWN: Dict[str, Tuple[str, str]] = {
    "web/src/opscenter/cells/task-manager/Cell.svelte": ("huddle", "opscenter cell mounts HuddleBody"),
    "web/src/opscenter/cells/task-manager-mk2/Cell.svelte": ("huddle", "TM Mark II, a deliberate fork of the task manager cell (Joe, item 1096): mounts HuddleBody"),
    "web/src/opscenter/cells/task-manager-mk2-all/Cell.svelte": ("huddle", "TM Mark II all, a deliberate fork of the all task managers cell (Joe, item 1096): mounts HuddleBody and the aggregate key"),
    "web/src/opscenter/cells/task-manager-all/Cell.svelte": ("huddle", "opscenter cell mounts HuddleBody and the aggregate key"),
    "web/src/opscenter/cells/task-list/ListRow.svelte": ("huddle", "list widget row draws the huddle status mark and opens the item"),
    "web/src/opscenter/cells/task-list/ListRowOpen.svelte": ("huddle", "list widget row opens the huddle answer form and reply box in place"),
    "web/src/opscenter/cells/task-list/age.ts": ("huddle", "list widget row ages use the huddle message clock format"),
    "web/src/opscenter/cells/task-list/model.ts": ("huddle", "list widget rows are typed and ordered with huddle-model, status and density"),
    "web/src/opscenter/cells/task-list/placement.ts": ("huddle", "list widget copy menu reuses the huddle badge statuses and labels"),
    "web/src/opscenter/cells/task-list/state.svelte.ts": ("huddle", "list widget reads the huddle store"),
    "web/src/opscenter/cells/questions/model.ts": ("huddle", "questions cell types its rows with huddle-model"),
    "web/src/lib/attention-kinds/read.svelte.ts": ("huddle", "bell attention kinds read the huddle store (landed with #1627, after the audit)"),
    "web/src/lib/attention-kinds/rows.ts": ("huddle", "bell attention kinds type their rows with huddle-model (landed with #1627, after the audit)"),
    "web/src/lib/projects-shared/agent-offer.ts": ("huddle", "reads the huddle manifest and agent roster"),
    "web/src/lib/session-rail/alert-count-sources.svelte.ts": ("huddle", "alert count reads the huddle store"),
    "web/src/lib/swarm-board/board-data.svelte.ts": ("huddle", "swarm board reads the roster, colors, node looks and manifest"),
    "web/src/lib/swarm-board/AgentFace.svelte": ("huddle", "swarm board draws huddle swarm characters"),
    "web/src/lib/swarm-board/views/calendar/BoardKey.svelte": ("huddle", "swarm board draws huddle swarm characters"),
    "web/src/lib/swarm-board/views/swimlanes/LaneChat.svelte": ("huddle", "swarm lane embeds the huddle chat widget"),
    "web/src/lib/plugins-page/HuddleSwarmSettings.svelte": ("huddle", "plugins page embeds the huddle swarm settings form"),
    "web/src/lib/huddle-agent/agent-drawer.svelte.ts": ("huddle", "agent drawer is a huddle screen living in lib/"),
    "web/src/lib/huddle-agent/screen-host.ts": ("huddle", "agent screen is a huddle screen living in lib/"),
    "web/src/lib/huddle-agent/drawer-host.ts": ("huddle", "agent drawer host is a huddle screen living in lib/"),
    "web/src/lib/huddle-agent/HuddleAgentScreen.svelte": ("huddle", "agent screen is a huddle screen living in lib/"),
    "web/src/lib/huddle-agent/agent-dock.ts": ("huddle", "agent dock is a huddle screen living in lib/"),
    "web/src/lib/huddle-agent/AgentDrawer.svelte": ("huddle", "agent drawer is a huddle screen living in lib/"),
    "web/src/lib/launchpad/EditProjectModal.svelte": ("huddle", "project editor reads huddle list prefs and the manifest"),
    "web/src/lib/launchpad/project-actions.ts": ("huddle", "project actions write huddle list prefs"),
    "web/src/lib/sidebar-shell/leaders-source.svelte.ts": ("huddle", "sidebar leaders read the huddle roster"),
    "web/src/lib/task-manager-schedules/task-manager-scheduled.ts": ("huddle", "automations tab reads huddle model and schedule helpers"),
    "web/src/lib/task-manager-schedules/task-manager-addon.svelte.ts": ("huddle", "automations addon reads the huddle manifest"),
    "web/src/lib/huddle-swarm/screen-host.ts": ("huddle", "swarm page is a huddle screen living in lib/"),
    "web/src/lib/huddle-swarm/SwarmPage.svelte": ("huddle", "swarm page is a huddle screen living in lib/"),
    "web/src/popout/AgentPopout.svelte": ("huddle", "agent pop-out page draws the huddle agent chat frame"),
    "web/vitest.config.ts": ("huddle", "setupFiles names a huddle test setup file, so every web test run needs the folder"),
}


def plugin_ids() -> List[str]:
    base = ROOT / "src" / "cplugs"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and p.name not in PLATFORM_DIRS and (p / "__init__.py").exists())


def owner_of(rel: str, ids: Iterable[str]) -> str:
    for pid in ids:
        if rel.startswith((f"src/cplugs/{pid}/", f"web/src/cplugs/{pid}/")):
            return pid
    return ""


def python_reach(source: str, ids: Iterable[str]) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            names = [module] + [f"{module}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if len(parts) >= 3 and parts[:2] == ["src", "cplugs"] and parts[2] in ids:
                found.add(parts[2])
    return found


def web_reach(rel: str, source: str, ids: Iterable[str]) -> Set[str]:
    found: Set[str] = set()
    specs = [m.group(1) for m in SPECIFIER.finditer(source)]
    if rel.startswith("web/") and rel.count("/") == 1:
        specs += [m.group(1) for m in QUOTED_PLUGIN_PATH.finditer(source)]
    for spec in specs:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec)) if spec.startswith(".") else spec
        for pid in ids:
            if re.search(rf"(?:^|/)cplugs/{pid}(?:/|$)", resolved):
                found.add(pid)
    return found


def production_files() -> Iterable[Path]:
    for base in ("src", "scripts"):
        yield from (ROOT / base).rglob("*.py")
    for suffix in WEB_SUFFIXES:
        yield from (ROOT / "web" / "src").rglob(f"*{suffix}")
    yield from (ROOT / "web").glob("*.ts")


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return ".test." in name or name.endswith("-test-setup.ts") or "/__tests__/" in rel


def current_reach() -> Dict[str, Set[str]]:
    ids = plugin_ids()
    out: Dict[str, Set[str]] = {}
    for path in production_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in SEAMS or is_test_file(rel) or "node_modules" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        reached = python_reach(text, ids) if rel.endswith(".py") else web_reach(rel, text, ids)
        reached = {pid for pid in reached if owner_of(rel, ids) != pid}
        if reached:
            out[rel] = reached
    return out


def test_no_new_reach_into_a_plugin_folder():
    new = {rel: sorted(p) for rel, p in current_reach().items() if p - ({KNOWN[rel][0]} if rel in KNOWN else set())}
    assert new == {}, "code outside a plugin's folders imports it; put the code in the plugin or go through the sdk (docs/cplug-self-containment-audit.md)"


def test_known_list_only_shrinks():
    reach = current_reach()
    stale = sorted(rel for rel, (pid, _why) in KNOWN.items() if pid not in reach.get(rel, set()))
    assert stale == [], "these KNOWN entries no longer reach their plugin; delete them"


def test_known_entries_name_a_real_plugin_and_a_reason():
    ids = plugin_ids()
    assert [rel for rel, (pid, why) in KNOWN.items() if pid not in ids or not why.strip()] == []


def test_the_checks_can_fail_on_fixtures():
    ids = ["huddle", "flow"]
    assert python_reach("from src.cplugs.huddle.store import x\nimport src.cplugs.flow\nfrom src.cplugs import flow\n", ids) == {"huddle", "flow"}
    assert python_reach("from src.cplugs.sdk import x\nfrom . import huddle\nimport json\n", ids) == set()
    assert web_reach("web/src/lib/a.ts", "import x from '../cplugs/huddle/x';\nconst m = await import('../cplugs/flow');\n", ids) == {"huddle", "flow"}
    assert web_reach("web/src/lib/a.ts", "import m from '../../../src/cplugs/huddle/cplug.json';\n", ids) == {"huddle"}
    assert web_reach("web/src/lib/a.ts", "import x from '../cplugs/sdk';\nimport s from 'svelte';\n", ids) == set()
    assert web_reach("web/vitest.config.ts", "setupFiles: ['src/cplugs/huddle/setup.ts']", ids) == {"huddle"}
    assert owner_of("web/src/cplugs/huddle/a.ts", ids) == "huddle" and owner_of("web/src/lib/a.ts", ids) == ""
