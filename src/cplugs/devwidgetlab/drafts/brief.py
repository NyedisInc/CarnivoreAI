
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

RULES = """\
## Rules

- Work ONLY inside this folder. `files/` mirrors the repo: `files/web/src/opscenter/cells/<name>/Cell.svelte` is this draft's copy of that file.
  Copy a repo file into `files/` at the same path before changing it; the Widget Lab preview uses your copy in place of the real one.
- The repo checkout at `{repo}` is a READ-ONLY reference (conventions, neighbors, `docs/widget-spec.md` (section 11 first), `docs/widget-lab.md`,
  `docs/widget-system.md` section 25). Do not edit it, commit to it or push anything.
- Use the Military Terminal look: `--oc-*` tokens only, mono type, hairlines, no hardcoded colors. Every user-visible string comes from the string
  catalog (`client/js/i18n/catalog.en.js`); in a draft a literal in the cell is fine and is moved to the catalog at ship.
- A widget ships fixtures: a `data` and an `empty` pair, in `files/web/src/opscenter/widgets/fixtures/`. The cell is handed its measured box and
  nothing else (`web/src/opscenter/lib/cell.ts`).
- Preview: the Widget Lab (the slide-out menu, the DRAFTS group) builds this folder and shows it live beside the current widget. Ask for a build
  there, or ask the person to.
- NOTHING LANDS FROM HERE. Shipping is a separate step through the widget's Task Manager item and the owner's tick. Say what is ready; do not ship.

## Chrome and menus (`docs/widget-spec.md` section 11; references: Notes for the chrome, Session Resources for declared controls)

- [ ] The cell is built on the widget shell (`docs/widget-spec.md` section 13, "The widget shell"), as the starter cell is: `defineWidget` in
  its module script (id, scope, actions, `state`), `useWidget` in the component and the body inside `<WidgetShell>`. The shell does the header
  hand-up, the declared menu actions and the loading, empty and error sentences; do not wire them by hand.
- [ ] Every view value the widget remembers (a mode, a fold, a sort) is a field of the definition's `state`, with a default and a validator
  (section 12, "Statefulness"); `state: {{}}` says it remembers nothing. A session widget with an all sessions sibling gets its this session |
  all sessions switch in the menu from the host; the cell draws none.
- [ ] The body draws no title, no close, no gear and NO KEBAB or other menu button. The host draws the one widget menu. (Only the terminal keeps a
  kebab; a "+" add button that opens things to create is allowed when its items are also declared.)
- [ ] Every control goes UP into the host header while it is drawn (`WidgetShell`'s `controls`, as `cells/notes/Cell.svelte` does); a body row of
  controls only where no header is drawn, and in a bar slide-out at most one corner icon.
- [ ] Every control, toggle, view and filter is ALSO an action of the definition, so `useWidget` declares it to the one widget menu
  (`declareWidgetActions`); a persistent choice is a `settings` entry in the widget's manifest, never a private body toggle.
- [ ] The widget's one menu opens from its icon on the rail and from the icon at the top left of its title strip (click, right-click, Shift+F10 on the
  focused icon). The host owns both icons, so a draft draws nothing for it. Rows get NO menu of their own (an item
  message 5597); no action is reachable only by a modifier (Shift+click): it is a widget menu item.
- [ ] Mounting the cell only READS: no write, nothing created, no focus taken until the owner acts. The rail icon's menu mounts the cell unseen while
  its panel is closed so the declared actions are there (`docs/widget-spec.md` section 11 rule 5); a widget that owns a live pane declares `keepAlive`
  or a live-pane capability and is never mounted unseen.
- [ ] Every menu id takes its letter from `client/js/menu-keys.js` `LETTERS`; a new meaning gets a registered letter at ship, never a per-menu one.
- [ ] The "Menu map" table below is filled in: every action, and where it is reached.
- [ ] The checks pass: the static ones (`MENU_CONFORMANCE_ROOT=<this folder>/files/web/src/opscenter/cells npx vitest run
  src/opscenter/widgets/menu/menu-conformance.test.ts` and `SHELL_CONFORMANCE_ROOT=<this folder>/files/web/src/opscenter/cells npx vitest run
  src/opscenter/widgets/shell/shell-conformance.test.ts` from the checkout's `web/`) and the preview's menu findings (`menu-button-in-body`), which the Widget Lab lists under the preview and the gate fails on.
"""


MENU_MAP = """\
## Menu map

Every action the widget offers, and where a person reaches it. Every control of the body appears here; an action with no menu entry
is a defect. Letters come from `client/js/menu-keys.js` `LETTERS`.

| action | menu id | header control | widget menu | letter |
|---|---|---|---|---|
| (fill in) | | | | |

"""


def _list(items: List[str]) -> str:
    return ", ".join(items) if items else "none"


def compose_new(repo: Path, slug: str, title: str, what: str, hosts: List[str], sizes: List[str], category: str) -> str:
    return (f"# New widget: {title}\n\nDraft `{slug}` / widget id `core.{slug}` / category {category}\n\n"
            f"## What it shows\n\n{what.strip() or '(not written yet)'}\n\n"
            f"## Where it goes\n\nHosts: {_list(hosts)}. Sizes it calls out: {_list(sizes)}.\n\n"
            "## Starter files already here\n\n- `files/web/src/opscenter/cells/" + slug + "/Cell.svelte`: the cell stub\n"
            "- `files/web/src/opscenter/widgets/fixtures/core." + slug + ".ts`: the data and empty fixtures\n"
            "- `widget.json`: the manifest entry (title, hosts, sizes, the cell record, the fit declaration, and the options a built-in has: `settings`, `scope`, `looks`, `keepAlive`, `views`; null is none)\n"
            "- `contract.json`: the `src/data/widget-contracts.json` record\n\n" + MENU_MAP + RULES.format(repo=repo))


def compose_revision(repo: Path, slug: str, widget: str, title: str, change: str, context: Dict[str, Any]) -> str:
    lines = [f"# Revision: {title}", "", f"Draft `{slug}` revises `{widget}`.", "", "## What should change", "", change.strip() or "(not written yet)", ""]
    if context:
        lines += ["## What was on show", ""] + [f"- {key}: {value}" for key, value in context.items()] + [""]
    lines += ["## Files", "", "This folder holds only what changes. Copy the repo file you change into `files/` at its repo path first.", ""]
    return "\n".join(lines) + "\n" + MENU_MAP + RULES.format(repo=repo)


_REPO_LINE = re.compile(r"The repo checkout at `[^`]*`")


def retarget(brief_path: Path, repo: Path) -> None:
    try:
        text = brief_path.read_text(encoding="utf-8")
    except OSError:
        return
    fixed = _REPO_LINE.sub(lambda _m: f"The repo checkout at `{repo}`", text)
    if fixed != text:
        brief_path.write_text(fixed, encoding="utf-8")
