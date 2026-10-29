
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from src.cplugs.devwidgetlab.drafts import brief, store
from src.cplugs.devwidgetlab.errors import DraftInvalid

GRID_SIZES = ("small", "wide", "tall", "medium", "large", "full")
NEW_HOSTS = ("home", "terminal", "drawer", "popout")
CATEGORIES = ("overview", "sessions", "catalog", "monitoring", "tools", "live")
ID_PATTERN = re.compile(r"^core\.[a-z][a-z0-9-]{1,39}$")
CELL_PATH = "web/src/opscenter/cells/{slug}/Cell.svelte"
FIXTURES_PATH = "web/src/opscenter/widgets/fixtures/core.{slug}.ts"

CELL_STUB = '''<script lang="ts" module>
  import {{ defineWidget }} from '../../widgets/shell/define-widget.svelte';

  /**
   * The draft's definition (`docs/widget-spec.md` section 13, "The widget shell"): its id, whether it is about one session or none,
   * its menu actions (each id takes its letter from `client/js/menu-keys.js` `LETTERS`) and the view state it remembers (section 12,
   * "Statefulness"; `state: {{}}` says it remembers nothing). Change the scope to 'session' for a widget about one session.
   */
  export const DRAFT_WIDGET = defineWidget({{
    id: 'core.{slug}',
    scope: 'global',
    actions: [{{ id: 'show-path', labelKey: 'widget.starter.show_path', kind: 'switch' }}],
    state: {{ 'show-path': {{ home: 'device', default: false, valid: (value: unknown): value is boolean => typeof value === 'boolean' }} }},
  }});
</script>

<script lang="ts">
  /**
   * {title}: {what}
   *
   * Description: a draft cell (Widget Lab). Replace the sample rows; keep the definition, the binding and the shell. The cell is
   *   handed its measured box and nothing else (`opscenter/lib/cell.ts`), so it never reads the window.
   *
   *   THE WIDGET SHELL (`docs/widget-spec.md` section 13). `useWidget` binds the definition above: it declares the actions to the
   *   ONE widget menu (the host draws it, from the icon on the rail and the icon at the top left of its title strip; this body
   *   draws no menu and NO kebab), and it keeps the declared view state. `WidgetShell` puts the controls UP into the host header
   *   while that header is drawn and in the body otherwise, and draws the loading, empty and error sentences. Persistent choices
   *   are settings in the widget's manifest, not body toggles.
   * Inputs (props): width, height (css px of the body); meta (the cell record); phone (one-up phone stack); limit (rows before "show more").
   */
  import type {{ CellProps }} from '../../lib/cell';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import {{ useWidget, type WidgetHandle }} from '../../widgets/shell/define-widget.svelte';
  import {{ t }} from '../../../lib/i18n/index.svelte';

  let props: CellProps = $props();

  /** Sample rows: replace with what the widget shows. */
  const ROWS = [{{ id: 'first', name: 'first row', path: '/sample/first' }}, {{ id: 'second', name: 'second row', path: '/sample/second' }}];
  let copied = $state<string | null>(null);

  /** What a row's click does (here: copy its path). Inputs: row. Output: void. */
  function copyPath(row: (typeof ROWS)[number]): void {{
    copied = row.id;
    void navigator.clipboard?.writeText(row.path);
  }}

  // Every declared action is bound here; the header control and the menu item run the same function.
  const widget: WidgetHandle<typeof DRAFT_WIDGET> = useWidget(DRAFT_WIDGET, () => props, () => ({{ 'show-path': {{ on: showPath, run: togglePath }} }}));
  /** Whether rows show their path: remembered per device by the declared state. */
  const showPath: boolean = $derived(widget.state['show-path']);

  /** Flip the path view (the owner's change is what writes it). Inputs: none. Output: void. */
  function togglePath(): void {{
    widget.state['show-path'] = !showPath;
  }}
</script>

{{#snippet controls(place: 'header' | 'body' | 'corner')}}
  <button type="button" class="oc-ibtn oc-ibtn--bare" data-place={{place}} aria-pressed={{showPath}} aria-label={{t('widget.starter.show_path')}} onclick={{togglePath}}>path</button>
{{/snippet}}

<WidgetShell {{widget}} {{controls}}>
  <div class="draft-cell" data-draft-widget="{slug}">
    <p class="draft-cell__label">{title_attr} {{props.width}} x {{props.height ?? 'auto'}}</p>
    <ul class="draft-cell__rows">
      {{#each ROWS as row (row.id)}}
        <li class="draft-cell__row" class:draft-cell__row--on={{copied === row.id}}>
          <button type="button" class="draft-cell__hit" onclick={{() => copyPath(row)}}>{{showPath ? row.path : row.name}}</button>
        </li>
      {{/each}}
    </ul>
  </div>
</WidgetShell>

<style>
  .draft-cell {{
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 12px;
    font-family: var(--font-mono);
    color: var(--oc-text);
  }}
  .draft-cell__label {{
    margin: 0;
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--oc-text-muted);
  }}
  .draft-cell__rows {{
    margin: 0;
    padding: 0;
    list-style: none;
  }}
  .draft-cell__hit {{
    width: 100%;
    padding: 2px 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    font-size: 12px;
    text-align: left;
    cursor: pointer;
  }}
  .draft-cell__row--on .draft-cell__hit {{
    color: var(--oc-cyan);
  }}
</style>
'''

FIXTURES_STUB = '''/**
 * Fixtures for the {title} draft (`{wid}`).
 *
 * Description: the API answers the cell is drawn from, keyed `METHOD /path` under `/api/v1` (see `fixtures/types.ts`). `data` is a typical
 *   answer, `empty` is nothing yet. Every widget ships both.
 */
import type {{ WidgetFixtures }} from './types';

export const {export_name}: WidgetFixtures = {{
  data: {{}},
  empty: {{}},
}};
'''


def camel(slug: str) -> str:
    head, *tail = slug.split("-")
    return head + "".join(part.capitalize() for part in tail)


def cell_record(slug: str) -> Dict[str, Any]:
    return {
        "phoneOrder": 60, "titleKey": f"opscenter.cell.{slug.replace('-', '_')}.title", "icon": "grid", "iconTone": "oc-cyan",
        "showCount": False, "chrome": "card", "titleHeight": 31, "defaultRow": "r3", "defaultIndex": 20, "defaultFr": 0.3,
        "defaultHeight": 200, "minPx": 220, "minHeight": 88,
        "widthStates": [{"name": "name", "min": 220}], "heightStates": [{"name": "title", "min": 0}, {"name": "rows", "min": 88}],
    }


def check_new_request(name: str, hosts: List[str], sizes: List[str], category: str) -> None:
    if not hosts or any(h not in NEW_HOSTS for h in hosts):
        raise DraftInvalid(f"hosts are from {', '.join(NEW_HOSTS)}")
    if not sizes or any(s not in GRID_SIZES for s in sizes):
        raise DraftInvalid(f"sizes are from {', '.join(GRID_SIZES)}")
    if category not in CATEGORIES:
        raise DraftInvalid(f"category is one of {', '.join(CATEGORIES)}")
    if not name.strip():
        raise DraftInvalid("a new widget needs a name")


MANIFEST_OPTIONS = ("settings", "scope", "looks", "keepAlive", "views")


def widget_record(slug: str, title: str, hosts: List[str], sizes: List[str], category: str) -> Dict[str, Any]:
    wid = f"core.{slug}"
    return {"id": wid, "slot": slug, "title": title, "category": category, "type": "list", "capabilities": [], "instancing": "singleton",
            "hosts": hosts, "fits": {"sizes": sizes, "anySize": True, "max_per_surface": 1},
            **{option: None for option in MANIFEST_OPTIONS},
            "cell": cell_record(slug), "fixtures_export": f"{camel(slug)}Fixtures",
            "paths": {"cell": CELL_PATH.format(slug=slug), "fixtures": FIXTURES_PATH.format(slug=slug)}}


def contract_record(slug: str, title: str, hosts: List[str], sizes: List[str]) -> Dict[str, Any]:
    wid = f"core.{slug}"
    return {"kind": "widget", "id": wid, "name": title, "version": "1.0.0", "api_version": 1, "min_app_version": "1.16.1", "author": "Carnivore",
            "tier": "builtin", "scope": ["global"], "source": "builtin", "declarative": False, "instancing": "singleton", "sizes": sizes,
            "any_size": True, "hosts": hosts, "reads": [], "fixtures": ["data", "empty"], "fixture": wid, "max_per_surface": 1}


def write_new(folder: Path, slug: str, title: str, what: str, hosts: List[str], sizes: List[str], category: str) -> List[str]:
    check_new_request(title, hosts, sizes, category)
    wid = f"core.{slug}"
    if not ID_PATTERN.match(wid):
        raise DraftInvalid("that name does not make a legal widget id")
    record = widget_record(slug, title, hosts, sizes, category)
    mirror = folder / store.MIRROR_FOLDER
    cell = mirror / store.mirror_target(CELL_PATH.format(slug=slug))
    fixtures = mirror / store.mirror_target(FIXTURES_PATH.format(slug=slug))
    cell.parent.mkdir(parents=True, exist_ok=True)
    fixtures.parent.mkdir(parents=True, exist_ok=True)
    cell.write_text(CELL_STUB.format(title=title, what=what.strip().splitlines()[0] if what.strip() else "what it shows.", slug=slug,
                                     title_attr=title.replace("<", "").replace("{", "").replace("}", "")), encoding="utf-8")
    fixtures.write_text(FIXTURES_STUB.format(title=title, wid=wid, export_name=record["fixtures_export"]), encoding="utf-8")
    store.write_json(folder / "widget.json", record)
    store.write_json(folder / "contract.json", contract_record(slug, title, hosts, sizes))
    (folder / store.BRIEF_FILE).write_text(brief.compose_new(store.root_of(folder), slug, title, what, hosts, sizes, category), encoding="utf-8")
    store.write_overrides_note(folder, store.read_record(folder))
    return sorted(["widget.json", "contract.json", store.BRIEF_FILE, store.OVERRIDES_FILE, *(f"{store.MIRROR_FOLDER}/{p}" for p in store.mirrored_files(folder))])


def write_revision_note(folder: Path, slug: str, widget: str, title: str, change: str, context: Dict[str, Any]) -> List[str]:
    (folder / store.BRIEF_FILE).write_text(brief.compose_revision(store.root_of(folder), slug, widget, title, change, context), encoding="utf-8")
    store.write_overrides_note(folder, store.read_record(folder))
    return [store.BRIEF_FILE, store.OVERRIDES_FILE]
