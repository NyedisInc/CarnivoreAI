import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { DIALOG_OPT_OUT, HOST_RULES, ZONE_LAYER_DIRS, ZONE_LAYER_FILES, scanHosts, scanRules, scanZoneLayer, type HostFinding, type HostSource } from './host-scan';

const SRC = fileURLToPath(new URL('../..', import.meta.url));

const KNOWN: readonly string[] = [
  'lib/widgets-page/PlaceDock.svelte:intersection-observer',
];

/** The most KNOWN may hold. Lower it with the list, never raise it. */
const KNOWN_CEILING = 1;

const KEY_KNOWN: readonly string[] = [
  'cplugs/devwidgetlab/DockBar.svelte:key-button',
  'cplugs/devwidgetlab/DockBar.svelte:menu-key-literal',
];

const KEY_KNOWN_CEILING = 2;

const TAB_KNOWN: readonly string[] = [
  'cplugs/huddle/agents/AgentChatFrame.svelte:page-tabs',
];

const TAB_KNOWN_CEILING = 1;

const DIALOG_KNOWN: readonly string[] = [
  'cplugs/huddle/TaskManagerArtifactDialog.svelte:dialog-frame',
  'cplugs/huddle/TaskManagerForkDialog.svelte:dialog-frame',
  'cplugs/huddle/TaskManagerScheduleEditor.svelte:dialog-frame',
  'cplugs/huddle/TaskManagerSend.svelte:dialog-frame',
  'cplugs/huddle/TaskManagerTickConfirm.svelte:dialog-frame',
  'lib/catalog/ItemNotePopup.svelte:dialog-frame',
];

const DIALOG_KNOWN_CEILING = 6;

const PAGE_ROW_MENU_KNOWN: readonly string[] = [
  'lib/sessions-page/PanelHead.svelte:page-row-menu',
];

const PAGE_ROW_MENU_CEILING = 1;

const ALLOWED: readonly string[] = [...KNOWN, ...KEY_KNOWN, ...TAB_KNOWN, ...DIALOG_KNOWN, ...PAGE_ROW_MENU_KNOWN];

/** Every non-test source file under a folder, paths relative to `web/src/`. Inputs: dir, base. Output: HostSource[]. */
function sourcesOf(dir: string, base = ''): HostSource[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    const rel = base ? `${base}/${entry.name}` : entry.name;
    if (entry.isDirectory()) return ['fixtures', '__goldens__', 'node_modules'].includes(entry.name) ? [] : sourcesOf(full, rel);
    if (!/\.(svelte|ts)$/.test(entry.name) || /\.(test|spec)\./.test(entry.name)) return [];
    return [{ path: rel, text: fs.readFileSync(full, 'utf8') }];
  });
}

/** A finding as `path:rule`. Inputs: finding. Output: string. */
const keyOf = (f: HostFinding): string => `${f.path}:${f.rule}`;

describe('host work stays in the zone shell', () => {
  const sources = sourcesOf(SRC);
  const found = scanHosts(sources).map(keyOf);

  it('looked at the tree (a scan of nothing is not a pass)', () => {
    expect(sources.length).toBeGreaterThan(200);
  });

  it('has no offender outside KNOWN', () => {
    expect(found.filter((one) => !ALLOWED.includes(one)), 'call the shell (placement-resolve.ts, TabKey.svelte, key-nav.ts) instead of copying host work; never add to KNOWN').toEqual([]);
  });

  it('keeps every KNOWN row true (fixed code leaves the list)', () => {
    expect(ALLOWED.filter((one) => !found.includes(one))).toEqual([]);
  });

  it('only shrinks', () => {
    expect(KNOWN.length).toBe(KNOWN_CEILING);
    expect(KEY_KNOWN.length).toBe(KEY_KNOWN_CEILING);
    expect(TAB_KNOWN.length).toBe(TAB_KNOWN_CEILING);
    expect(DIALOG_KNOWN.length).toBe(DIALOG_KNOWN_CEILING);
    expect(PAGE_ROW_MENU_KNOWN.length).toBe(PAGE_ROW_MENU_CEILING);
  });

  it('keeps every DIALOG_OPT_OUT file true: it still draws the frame it is excused for, and each has a reason', () => {
    const rule = HOST_RULES.find((one) => one.name === 'dialog-frame')!;
    const files = sources.filter((one) => one.path in DIALOG_OPT_OUT);
    expect(files.map((one) => one.path).sort()).toEqual(Object.keys(DIALOG_OPT_OUT).sort());
    expect(scanRules([{ ...rule, owners: [] }], files).map((one) => one.path).sort()).toEqual(Object.keys(DIALOG_OPT_OUT).sort());
    for (const reason of Object.values(DIALOG_OPT_OUT)) expect(reason.length).toBeGreaterThan(40);
  });

  it('goes red on a hand-drawn dialog frame, and not on the two frames, a role handed to them, Elite, a selector or a comment', () => {
    const planted = scanHosts([
      { path: 'lib/x/Dialog.svelte', text: '<div class="x popup-focus" role="dialog" aria-label="x">body</div>' },
      { path: 'lib/x/Alert.svelte', text: '<section\n  class="x"\n  onclick={() => go()}\n  role="alertdialog">' },
      { path: 'lib/x/Modal.svelte', text: '<div class="modal-overlay" aria-modal="true">' },
      { path: 'lib/launchpad/ModalShell.svelte', text: '<div class="modal-overlay" {role} aria-modal="true">' },
      { path: 'lib/dialog-frame/AnchoredPopup.svelte', text: '<div class="popup-focus" role="dialog">' },
      { path: 'lib/x/Uses.svelte', text: '<ModalShell title="x" role="alertdialog" onCancel={c}>body</ModalShell>' },
      { path: 'lib/elite/Sheet.svelte', text: '<div class="m1-sheet" role="dialog" aria-modal="true">' },
      { path: 'lib/x/Query.ts', text: "if (el.closest('[role=\"dialog\"], [aria-modal=\"true\"]')) return;" },
      { path: 'lib/x/Doc.svelte', text: '<!-- <div role="dialog"> -->\nexport const a = 1;' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/x/Alert.svelte:dialog-frame', 'lib/x/Dialog.svelte:dialog-frame', 'lib/x/Modal.svelte:dialog-frame']);
  });

  it('goes red on a page row with its own menu (ruling b), and not on the item menu or a row outside the pages', () => {
    const planted = scanHosts([
      { path: 'lib/sessions-page/Row.svelte', text: '<div class="sp-row" oncontextmenu={open}><SessionKebab session={s} /></div>' },
      { path: 'lib/deepsearch/Hit.svelte', text: '<RowMenu items={items} />' },
      { path: 'lib/sessions-search/Keys.ts', text: 'if (isMenuKey(event)) openMenu();' },
      { path: 'lib/item-menu/ItemMenu.svelte', text: '<div oncontextmenu={open}></div>' },
      { path: 'lib/projects-page/Row.svelte', text: '<div oncontextmenu={open}></div>' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/deepsearch/Hit.svelte:page-row-menu', 'lib/sessions-page/Row.svelte:page-row-menu', 'lib/sessions-search/Keys.ts:page-row-menu']);
  });

  it('lets the menu settings row hold the rail pin (ruling a) and no other menu file', () => {
    const planted = scanHosts([
      { path: 'lib/drawer-tabs/DrawerMenu.svelte', text: '<BarPin edge="rail" />' },
      { path: 'lib/drawer-tabs/OtherMenu.svelte', text: '<BarPin edge="rail" />' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/drawer-tabs/OtherMenu.svelte:bar-pin']);
  });

  it('goes red on a hand-drawn key and a spelled menu key, and not on the key itself, a selector or a query', () => {
    const planted = scanHosts([
      { path: 'lib/x/Key.svelte', text: '<button type="button" class="rail__key" data-zone-item={id}>k</button>' },
      { path: 'lib/x/Tab.svelte', text: '<button class="oc-tab oc-tab-active" role="tab">t</button>' },
      { path: 'lib/x/Claw.svelte', text: '<button data-phone-tabs-claw onclick={go}>c</button>' },
      { path: 'lib/x/Menu.ts', text: "if (event.key === 'F10' && event.shiftKey) open();" },
      { path: 'lib/zone-shell/TabKey.svelte', text: '<button class="rail__key">k</button>' },
      { path: 'lib/zone-shell/key-nav.ts', text: "return event.key === 'ContextMenu';" },
      { path: 'lib/x/Css.svelte', text: '<style>.rail__key { color: red; } .oc-tab-icon {}</style><span class="oc-tab-icon"></span>' },
      { path: 'lib/x/Query.ts', text: "el.querySelector('.rail__key, [data-rail-settings]'); const RAIL_BUSY = '.rail__key';" },
      { path: 'lib/x/Doc.svelte', text: '<!-- <button class="rail__key"> -->\n// the ContextMenu key\nexport const a = 1;' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/x/Claw.svelte:key-button', 'lib/x/Key.svelte:key-button', 'lib/x/Menu.ts:menu-key-literal', 'lib/x/Tab.svelte:key-button']);
  });

  it('goes red on a hand-drawn page tab strip, and not on Tabs itself, the terminal strip or a comment', () => {
    const planted = scanHosts([
      { path: 'lib/x/Strip.svelte', text: '<div class="my-tabs" role="tablist" aria-label="x"><button role="tab">a</button></div>' },
      { path: 'opscenter/ui/Tabs.svelte', text: '<div class="oc-ptabs__list" role="tablist">' },
      { path: 'opscenter/shell/TabStrip.svelte', text: '<div role="tablist">' },
      { path: 'lib/x/Doc.svelte', text: '<!-- <div role="tablist"> -->\nexport const a = 1;' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/x/Strip.svelte:page-tabs']);
  });

  it('goes red on a planted offender and ignores a comment naming one', () => {
    const planted = scanHosts([
      { path: 'lib/x/Planted.svelte', text: '<BarPin edge="side" />' },
      { path: 'lib/x/Action.ts', text: "void toggleBarPin('side'); const n = pinBarNode(true, () => {});" },
      { path: 'lib/x/Peek.ts', text: 'const core = createPeekCore({});' },
      { path: 'lib/x/Doc.ts', text: "/** Example: CORE_MANIFESTS['core.notes'] */\n// activeScopeFor(m)\nexport const a = 1;" },
      { path: 'lib/x/Table.ts', text: 'const c = cellManifestFor(m, v, CORE_MANIFESTS);' },
      { path: 'lib/x/Handle.svelte', text: '<BarHandle edge="side" onpress={go} />' },
      { path: 'lib/zone-shell/ZoneHandle.svelte', text: '<BarHandle {edge} />' },
      { path: 'lib/x/Head.svelte', text: "const header = provideFrameHeader('notes-drawer');" },
    ]).map(keyOf);
    expect(planted).toEqual([
      'lib/x/Action.ts:bar-pin-action',
      'lib/x/Handle.svelte:bar-handle',
      'lib/x/Head.svelte:frame-header',
      'lib/x/Peek.ts:peek-core',
      'lib/x/Planted.svelte:bar-pin',
      'lib/x/Table.ts:cell-manifest-core-table',
    ]);
  });
});

const ZONE_DATA_KNOWN: readonly string[] = [];

const ZONE_DATA_CEILING = 0;

describe('the zone layer reads stores and never waits on a frame', () => {
  const sources = sourcesOf(SRC);
  const found = scanZoneLayer(sources).map(keyOf);

  it('reads the layout files it binds (a missing path is not a pass)', () => {
    const paths = new Set(sources.map((one) => one.path));
    expect(ZONE_LAYER_FILES.filter((one) => !paths.has(one))).toEqual([]);
    expect(sources.filter((one) => one.path.startsWith('lib/zone-shell/')).length).toBeGreaterThan(8);
    for (const dir of ZONE_LAYER_DIRS) expect(sources.filter((one) => one.path.startsWith(dir)).length, dir).toBeGreaterThan(0);
  });

  it('has no offender outside ZONE_DATA_KNOWN', () => {
    expect(found.filter((one) => !ZONE_DATA_KNOWN.includes(one)), 'read a store (widget-spec section 14); never add to ZONE_DATA_KNOWN').toEqual([]);
  });

  it('keeps every ZONE_DATA_KNOWN row true and only shrinks', () => {
    expect(ZONE_DATA_KNOWN.filter((one) => !found.includes(one))).toEqual([]);
    expect(ZONE_DATA_KNOWN.length).toBe(ZONE_DATA_CEILING);
  });

  it('goes red on a planted fetch, interval, socket and frame wait, and skips a comment and a method', () => {
    const planted = scanZoneLayer([
      { path: 'lib/zone-shell/A.svelte', text: 'const r = await fetch(url); setInterval(tick, 1000); const s = new WebSocket(u);' },
      { path: 'lib/zone-shell/B.ts', text: 'requestAnimationFrame(() => go());' },
      { path: 'lib/session-rail/SessionRail.svelte', text: 'await authFetch(url); requestAnimationFrame(f);' },
      { path: 'lib/zone-shell/C.ts', text: '// fetch(url) and setInterval(f)\nconst a = store.fetch(1); const b = prefetch(2);' },
      { path: 'lib/other/D.ts', text: 'fetch(url)' },
      { path: 'lib/session-list/E.svelte', text: 'setInterval(poll, 5000);' },
      { path: 'lib/drawer-layout/F.ts', text: 'await authFetch("/x");' },
      { path: 'lib/sidebar-shell/SidebarList.svelte', text: 'await fetch("/sessions/list");' },
    ]).map(keyOf);
    expect(planted).toEqual([
      'lib/drawer-layout/F.ts:data-fetch',
      'lib/session-list/E.svelte:data-interval',
      'lib/session-rail/SessionRail.svelte:data-fetch',
      'lib/sidebar-shell/SidebarList.svelte:data-fetch',
      'lib/zone-shell/A.svelte:data-fetch',
      'lib/zone-shell/A.svelte:data-interval',
      'lib/zone-shell/A.svelte:data-socket',
      'lib/zone-shell/B.ts:frame-wait',
    ]);
  });

  it('refuses a document key listener in the rails and a retired badge class anywhere', () => {
    const planted = scanHosts([
      { path: 'lib/sidebar-widgets/Esc.ts', text: "doc.addEventListener('keydown', onKey, true);" },
      { path: 'lib/mini-rail/Esc.ts', text: 'window.addEventListener("keydown", f)' },
      { path: 'lib/session-rail/Esc.ts', text: "document.addEventListener('keydown', f)" },
      { path: 'lib/widget-bars/Esc.ts', text: "window.addEventListener('keydown', f)" },
      { path: 'lib/widget-bars/strip-escape.svelte.ts', text: "window.addEventListener('keydown', f)" },
      { path: 'lib/other/Esc.ts', text: "document.addEventListener('keydown', f)" },
      { path: 'lib/sidebar-widgets/Panel.ts', text: "panel.addEventListener('keydown', f); // document.addEventListener('keydown', f)" },
      { path: 'lib/x/Old.svelte', text: '<span class="sbr-rail__badge"></span><span class="mr-key-badge"></span>' },
      { path: 'lib/zone-shell/ZoneBadge.svelte', text: '<span class="zone-badge"></span>' },
    ]).map(keyOf);
    expect(planted).toEqual([
      'lib/mini-rail/Esc.ts:document-keydown',
      'lib/session-rail/Esc.ts:document-keydown',
      'lib/sidebar-widgets/Esc.ts:document-keydown',
      'lib/widget-bars/Esc.ts:document-keydown',
      'lib/x/Old.svelte:badge-class',
    ]);
  });

  it('refuses a real browser observer and a stray tab-pane provider', () => {
    const planted = scanHosts([
      { path: 'lib/x/Obs.ts', text: 'const o = new IntersectionObserver(cb);' },
      { path: 'lib/x/Pane.svelte', text: 'provideTabPane({ active: true })' },
      { path: 'lib/zone-shell/ZonePane.svelte', text: 'provideTabPane({ active: true }); adoptFrameHeader(h);' },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/x/Obs.ts:intersection-observer', 'lib/x/Pane.svelte:tab-pane']);
  });

  it('refuses a second parser of the widget: tab prefix (slice 8b)', () => {
    const planted = scanHosts([
      { path: 'opscenter/engine/widget-tabs.ts', text: "export const WIDGET_TAB_PREFIX = 'widget:';" },
      { path: 'opscenter/cells/terminal-group/Stray.ts', text: "if (tab.startsWith('widget:')) return tab.slice(7);" },
    ]).map(keyOf);
    expect(planted).toEqual(['opscenter/cells/terminal-group/Stray.ts:widget-tab-parse']);
  });

  it('refuses a loose mount into a drawer region outside the drawer layout (slice 9c)', () => {
    const planted = scanHosts([
      { path: 'lib/drawer-tabs/mount-drawer-tabs.ts', text: 'if (el) mountPanel(DRAWER_TABBODY_ID, DynamicTabBody); mountPanel(DRAWER_LEDGER_ID, DrawerZone);' },
      { path: 'lib/x/Loose.ts', text: "mountPanel('session-sidebar-rail', MiniRail);" },
      { path: 'lib/drawer-layout/mount-drawer-layout.ts', text: 'mountPanel(DRAWER_AREA_BAR_ID, WidgetAreaBar);' },
      { path: 'lib/x/Other.ts', text: "mountPanel('version-banner', Banner);" },
    ]).map(keyOf);
    expect(planted).toEqual(['lib/drawer-tabs/mount-drawer-tabs.ts:drawer-mount', 'lib/x/Loose.ts:drawer-mount']);
  });

  it('refuses the retired terminal-group pane file, and not the phone pane', () => {
    const planted = scanHosts([
      { path: 'opscenter/cells/terminal-group/Cell.svelte', text: "import TabPane from './TabPane.svelte';" },
      { path: 'opscenter/phone-tabs-host.ts', text: "import PhoneTabPane from './phone/PhoneTabPane.svelte';" },
    ]).map(keyOf);
    expect(planted).toEqual(['opscenter/cells/terminal-group/Cell.svelte:tab-pane-component']);
  });
});
