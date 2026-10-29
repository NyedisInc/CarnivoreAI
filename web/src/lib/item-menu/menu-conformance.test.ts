import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(__dirname, '../../../..');

const SURFACE = 'a menu of its own surface (a dropdown or a page menu), not yet an item type';
const LEGACY = 'legacy client/js menu, on its way out with client/js';
const HARNESS = 'developer harness or style guide specimen';

const MARKUP_KNOWN: Record<string, string> = {
    'client/js/fab-menu.js': LEGACY,
    'client/js/header-menu.js': LEGACY,
    'client/js/session-theme-menu.js': LEGACY,
    'web/src/cplugs/devwidgetlab/PointerMenu.svelte': HARNESS,
    'web/src/cplugs/huddle/swarm/NodeMenu.svelte': SURFACE,
    'web/src/lib/automations/RowMenu.svelte': SURFACE,
    'web/src/lib/catalog/AddSplit.svelte': SURFACE,
    'web/src/lib/catalog/KeyHelp.svelte': SURFACE,
    'web/src/lib/deepsearch/HitActions.svelte': SURFACE,
    'web/src/lib/drawer-hud/AccountMenu.svelte': SURFACE,
    'web/src/lib/drawer-tabs/DrawerSearch.svelte': SURFACE,
    'web/src/lib/drawer-tabs/NewSessionButton.svelte': SURFACE,
    'web/src/lib/drawer-tabs/ViewMenu.svelte': SURFACE,
    'web/src/lib/notifications/mute/mute-control.ts': SURFACE,
    'web/src/lib/sidebar-widgets/RailMenu.svelte': SURFACE,
    'web/src/lib/sidebar-widgets/SidebarFlyoutHost.svelte': SURFACE,
    'web/src/lib/warroom/WarroomModal.svelte': SURFACE,
    'web/src/lib/widgets-page/PlaceMenu.svelte': 'the widgets page place picker (Alex (Example-owner), #2055, landed on master beside this ratchet): picks a place or a widget, belongs to no item',
    'web/src/lib/zone-shell/DeclaredTabMenu.svelte': 'a widget host: draws its own CascadeMenu for placement, nodes from widget-nodes.ts',
    'web/src/lib/zone-shell/PlacementMenuHost.svelte': 'a widget host: draws its own CascadeMenu for placement, nodes from widget-nodes.ts',
    'web/src/opscenter/cells/running-sessions/Cell.svelte': SURFACE,
    'web/src/opscenter/cells/terminal-group/Cell.svelte': SURFACE,
    'web/src/opscenter/cells/terminal-live/TerminalActions.svelte': 'the terminal cell options popover; its "actions" row folds out the session row menu through the model (row-menu.ts)',
    'web/src/opscenter/layout-editor/EmptySpaceMenu.svelte': SURFACE,
    'web/src/opscenter/layouts/LayoutCommandBar.svelte': SURFACE,
    'web/src/opscenter/layouts/LayoutTabs.svelte': SURFACE,
    'web/src/opscenter/phone/PhoneTabs.svelte': SURFACE,
    'web/src/opscenter/shell/HomeOpenMenu.svelte': SURFACE,
    'web/src/opscenter/ui/SortControl.svelte': SURFACE,
    'web/src/style-guide/specimens/TabStripSlot.svelte': HARNESS,
};

const MARKUP_OWNERS = ['web/src/lib/item-menu/ItemMenuHost.svelte', 'web/src/lib/drawer-tabs/CascadeMenu.svelte'];

const CONTEXT_KNOWN: Record<string, string> = {
    'client/js/touch-select.js': 'suppresses the browser menu during a touch text selection; opens no menu',
    'web/src/cplugs/devwidgetlab/DockBar.svelte': HARNESS,
    'web/src/cplugs/devwidgetlab/WidgetTree.svelte': HARNESS,
    'web/src/cplugs/huddle/swarm/SwarmOrg.svelte': SURFACE,
    'web/src/cplugs/huddle/swarm/SwarmPanel.svelte': SURFACE,
    'web/src/lib/browser/BrowserView.svelte': SURFACE,
    'web/src/lib/drawer-zone/DrawerZone.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/lib/drawer-zone/GlanceRow.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/lib/session-rail/SessionRail.svelte': SURFACE,
    'web/src/lib/sidebar-shell/row-interaction-play.ts': 'test play script that replays a recorded right-click on a row',
    'web/src/lib/sidebar-widgets/SidebarRailShell.svelte': SURFACE,
    'web/src/lib/warroom/WarRoomScreen.svelte': SURFACE,
    'web/src/lib/zone-shell/PlacementBody.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/lib/zone-shell/TabKey.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/opscenter/App.svelte': SURFACE,
    'web/src/opscenter/shell/CellFrame.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/opscenter/shell/CornerMenu.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/opscenter/shell/TabStrip.svelte': SURFACE,
    'web/src/opscenter/shell/WidgetHead.svelte': 'a widget surface: right-click opens the widget menu (a widget host)',
    'web/src/widget-harness/Harness.svelte': HARNESS,
};

const CONTEXT_OWNERS = ['web/src/lib/sidebar-shell/heading-events.ts', 'web/src/lib/sidebar-shell/row-events.ts', 'web/src/lib/item-menu/page-row.ts'];

function sources(rel: string, exts: string[]): string[] {
    const out: string[] = [];
    const walk = (dir: string): void => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (!['dist', 'node_modules', '__goldens__'].includes(entry.name)) walk(full);
            } else if (exts.some((e) => entry.name.endsWith(e)) && !/\.test\.ts$/.test(entry.name)) {
                out.push(path.relative(ROOT, full));
            }
        }
    };
    walk(path.join(ROOT, rel));
    return out.sort();
}

const SCANNER_RULE_FILES = [
    'web/src/lib/zone-shell/host-scan.ts',
    'web/src/opscenter/widgets/shell/shell-scan.ts',
    'web/src/opscenter/widgets/menu/cell-menu-scan.ts',
    'web/src/widget-harness/menu-conformance.ts',
];

const FILES = [...sources('web/src', ['.svelte', '.ts']), ...sources('client/js', ['.js'])].filter((f) => !SCANNER_RULE_FILES.includes(f));

function offenders(pattern: RegExp, owners: readonly string[]): string[] {
    return FILES.filter((f) => !owners.some((o) => f === o || (o.endsWith('/') && f.startsWith(o))))
        .filter((f) => pattern.test(code(fs.readFileSync(path.join(ROOT, f), 'utf8'))));
}

function code(source: string): string {
    return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '').replace(/^\s*\/\/.*$/gm, '');
}

const MARKUP = /<CascadeMenu\b|(?<!\[)role="menu"|role=\\"menu\\"|setAttribute\(\s*'role',\s*'menu'\)|(?<!\[)role='menu'/;
const RETIRED_ROW = /\b(?:window|w|g|g\(\)|rg\(\)|win|globalThis)\??\.SessionRowMenu(?:Items|Plugins|Open|Gestures|Shift)?\b(?!Actions|Sleep|Icons)|\bSessionRowMenu(?:Items|Plugins|Open|Gestures|Shift)?\?:|\/session-row-menu(?:-items|-plugins|-open|-gestures|-shift)?\.js['"]|['"]session-row-menu(?:-items|-plugins|-open|-gestures|-shift)?\.js['"]/;
const CONTEXT = /['"]contextmenu['"]|oncontextmenu/;

describe('menu markup is drawn by the one item menu host', () => {
    const found = offenders(MARKUP, MARKUP_OWNERS);
    it('the scan sees files (it can go red)', () => {
        expect(FILES.length).toBeGreaterThan(500);
        expect(SCANNER_RULE_FILES.filter((f) => !fs.existsSync(path.join(ROOT, f))), 'a left-out scanner file is gone').toEqual([]);
        expect(found.length).toBeGreaterThan(0);
    });
    it('no new file draws a menu of its own', () => {
        expect(found.filter((f) => !(f in MARKUP_KNOWN))).toEqual([]);
    });
    it('every MARKUP_KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(MARKUP_KNOWN).filter((f) => !found.includes(f))).toEqual([]);
    });
});

describe('a right-click opens the model, not a menu of its own', () => {
    const found = offenders(CONTEXT, CONTEXT_OWNERS);
    it('no new file handles a right-click', () => {
        expect(found.filter((f) => !(f in CONTEXT_KNOWN))).toEqual([]);
    });
    it('every CONTEXT_KNOWN row still applies (the list only shrinks)', () => {
        expect(Object.keys(CONTEXT_KNOWN).filter((f) => !found.includes(f))).toEqual([]);
    });
});

describe('item types are declared once, in the model', () => {
    it('a type is defined only under item-menu/menus/', () => {
        expect(offenders(/defineItemMenu\(/, ['web/src/lib/item-menu/menus/', 'web/src/lib/item-menu/registry.ts'])).toEqual([]);
    });
    it('the retired heading menu path does not come back', () => {
        expect(offenders(/showHeadingMenu|HeadingMenuEntry|heading-menu\.svelte|heading-menu-nodes|HeadingMenu\.svelte/, [])).toEqual([]);
    });
    it('the retired legacy row menu does not come back (its globals read, or its scripts loaded)', () => {
        expect(offenders(RETIRED_ROW, [])).toEqual([]);
        const pages = fs.readdirSync(path.join(ROOT, 'client')).filter((f) => f.endsWith('.html'));
        expect(pages.length, 'the page scan sees files').toBeGreaterThan(1);
        expect(pages.filter((f) => RETIRED_ROW.test(fs.readFileSync(path.join(ROOT, 'client', f), 'utf8')))).toEqual([]);
        expect(RETIRED_ROW.test("window.SessionRowMenuOpen.open(el)"), 'can go red on a global').toBe(true);
        expect(RETIRED_ROW.test('<script src="/static/js/session-row-menu.js"></script>'), 'can go red on a script tag').toBe(true);
        expect(RETIRED_ROW.test('g.SessionRowMenu?.contextFromTrigger?.(el)'), 'can go red on a typed globals read').toBe(true);
        expect(RETIRED_ROW.test('    SessionRowMenu?: { contextFromTrigger?(t: Element): unknown };'), 'can go red on a globals type').toBe(true);
        expect(RETIRED_ROW.test('window.SessionRowMenuActions.run(id, ctx)'), 'the run table that stays is not caught').toBe(false);
        expect(RETIRED_ROW.test('    SessionRowMenuActions?: { run?(): void };'), 'its type is not caught either').toBe(false);
    });
});
