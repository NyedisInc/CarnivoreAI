/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer, type LegacyWindow } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as Search from '../drawer/search';
import * as Bucketing from '../drawer/bucketing';
import { contextFromTrigger } from '../item-menu/row-context';
import { ctxOf, itemsOf } from '../item-menu/row-test-env';

const KindGroups = Bucketing as unknown as {
    kindOf(r: unknown): string; isBrowser(r: unknown): boolean;
    isAgentKind(r: unknown): boolean; folderLabel(r: unknown): string | null;
};

let Win: LegacyWindow;
const Menu = {
    contextFromTrigger: (el: { getAttribute: (n: string) => string | null }) => contextFromTrigger(el as unknown as Element)!,
    itemsFor: (c: Record<string, unknown>) => itemsOf(ctxOf(c)),
    uniqueShortcuts: (c: Record<string, unknown>): boolean => {
        const keys = itemsOf(ctxOf(c)).map((i) => i.shortcut).filter(Boolean);
        return new Set(keys).size === keys.length;
    },
};

beforeAll(() => {
    Win = loadLegacyDrawer();
});

beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
});

function body(rows: Record<string, any>[], arrangement?: { collapsed?: string[] } | null, opts?: { query?: string }): string {
    resetDrawer();
    const pinned = rows.filter((r) => r.is_pinned).map((r) => r.name);
    Store.save(pinned, rows.map((r) => r.name), (arrangement && arrangement.collapsed) || []);
    if (opts && opts.query) Search.setQuery(opts.query);
    return drawList(rows);
}

function fixtureRows() {
    return [
        {
            name: 'cloude_myapp', label: 'MyApp', is_pinned: false,
            agent_family: 'claude', project_id: 10, project_name: 'MyApp',
            working_dir: null, status: 'idle', created_by_cloude: true,
            session_id: null,
        },
        {
            name: 'cloude_myapp_shell', label: null, is_pinned: false,
            agent_family: 'shell', project_id: 10, project_name: 'MyApp',
            working_dir: '/Users/example/dev/myapp', status: 'unknown',
            created_by_cloude: true, session_id: null,
        },
        {
            name: 'cloude_console_home', label: null, is_pinned: true,
            agent_family: 'shell', project_id: 30, project_name: 'console-abc123',
            working_dir: '~', status: 'unknown', created_by_cloude: true,
            session_id: null,
        },
    ];
}

function sectionSlice(html: string, group: string): string {
    const markerIdx = html.indexOf(`data-group="${group}"`);
    if (markerIdx === -1) return '';
    const start = html.lastIndexOf('<div', markerIdx);
    let depth = 0;
    let i = start;
    while (i < html.length) {
        const nextOpen = html.indexOf('<div', i);
        const nextClose = html.indexOf('</div>', i);
        if (nextClose === -1) return html.slice(start);
        if (nextOpen !== -1 && nextOpen < nextClose) {
            depth += 1;
            i = nextOpen + 4;
        } else {
            depth -= 1;
            i = nextClose + 6;
            if (depth === 0) return html.slice(start, i);
        }
    }
    return html.slice(start);
}

function namesInGroup(html: string, group: string): string[] {
    const slice = sectionSlice(html, group);
    if (!slice) return [];
    return [...new Set([...slice.matchAll(/data-name="([^"]+)"/g)].map((x) => x[1] as string))];
}



it('kindOf: agent_family shell is a terminal, everything else is an agent', async () => {
    assert.equal(KindGroups.kindOf({ agent_family: 'shell' }), 'terminal');
    assert.equal(KindGroups.kindOf({ agent_family: 'claude' }), 'agent');
    assert.equal(KindGroups.kindOf({}), 'agent');
    assert.equal(KindGroups.kindOf(null), 'agent');
});

it('kindOf: a browser is row.kind === "browser" and nothing else', async () => {
    assert.equal(KindGroups.kindOf({ kind: 'browser' }), 'browser');
    assert.equal(KindGroups.isBrowser({ kind: 'browser' }), true);
    assert.equal(KindGroups.isAgentKind({ kind: 'browser' }), false);
    assert.equal(KindGroups.isBrowser({ agent_family: 'shell' }), false);
});

it('folderLabel: the working directory wins, the project name is the fallback, then null', async () => {
    assert.equal(KindGroups.folderLabel({ working_dir: '~', project_name: 'x' }), '~');
    assert.equal(KindGroups.folderLabel({ working_dir: null, project_name: 'MyApp' }), 'MyApp');
    assert.equal(KindGroups.folderLabel({ working_dir: null, project_name: null }), null);
    assert.equal(KindGroups.folderLabel({}), null);
});


function browserRow(overrides?: Record<string, unknown>): Record<string, any> {
    return Object.assign({
        name: 'browser:0123456789abcdef', kind: 'browser', browser_id: '0123456789abcdef',
        label: 'docs', url: 'https://example.com/a', status: 'live', is_pinned: false,
        project_id: null, project_name: null, working_dir: null,
    }, overrides || {});
}

it('a browser row lands in BROWSERS only, with a globe mark, its host, and no status light', async () => {
    const html = body([...fixtureRows(), browserRow()]);
    assert.deepEqual(namesInGroup(html, 'browsers'), ['browser:0123456789abcdef']);
    assert.ok(!namesInGroup(html, 'terminals').includes('browser:0123456789abcdef'));
    assert.ok(![...html.matchAll(/data-group="(p:[^"]+|rogue)"/g)].some((m) => namesInGroup(html, m[1] as string).includes('browser:0123456789abcdef')));
    const slice = sectionSlice(html, 'browsers');
    assert.match(slice, /data-browser-state="live"/);
    assert.match(slice, /session-sidebar-row-subtitle[^>]*>example\.com</);
    assert.match(slice, /data-row-menu-kind="browser"/);
    assert.ok(!/status-led|session-sidebar-group__project-led/.test(slice), 'no status light on the row or the header');
    assert.match(body([browserRow({ status: 'stopped' })]), /data-browser-state="stopped"/);
});

it('TERMINALS and BROWSERS headers draw no light at all, collapsed or not', async () => {
    const rows = [...fixtureRows(), browserRow()];
    const expanded = body(rows, { collapsed: [] });
    assert.ok(!/session-sidebar-group__project-led/.test(sectionSlice(expanded, 'terminals')),
        'TERMINALS expanded: no light');
    assert.ok(!/session-sidebar-group__project-led/.test(sectionSlice(expanded, 'browsers')),
        'BROWSERS expanded: no light');
    const collapsed = body(rows, { collapsed: ['terminals', 'browsers'] });
    assert.ok(!/session-sidebar-group__project-led/.test(sectionSlice(collapsed, 'terminals')),
        'TERMINALS collapsed: still no light - #623 removes it, #625 never moves it');
    assert.ok(!/session-sidebar-group__project-led/.test(sectionSlice(collapsed, 'browsers')),
        'BROWSERS collapsed: still no light');
    const pinnedCollapsed = body(rows, { collapsed: ['pinned', 'p:10'] });
    assert.ok(sectionSlice(pinnedCollapsed, 'pinned').length > 0, 'setup: PINNED is drawn, with rows');
    assert.ok(!/session-sidebar-group__project-led/.test(sectionSlice(pinnedCollapsed, 'pinned')),
        'PINNED collapsed: no light');
    assert.match(sectionSlice(pinnedCollapsed, 'p:10'), /session-sidebar-group__project-led/,
        'control: a heading that does not opt out draws the light while collapsed');
});

it('a pinned browser row is duplicated into PINNED and stays under BROWSERS', async () => {
    const html = body([browserRow({ is_pinned: true })]);
    assert.deepEqual(namesInGroup(html, 'pinned'), ['browser:0123456789abcdef']);
    assert.deepEqual(namesInGroup(html, 'browsers'), ['browser:0123456789abcdef']);
});

it('a browser row menu offers pop out, rename, pin, move to group and close, and nothing that reaches tmux', async () => {
    const ctx = Menu.contextFromTrigger({ getAttribute: (() => {
        const html = body([browserRow()]);
        const trigger = html.match(/<button type="button" class="[^"]*" data-row-menu="[^>]*>/)![0];
        return (n: string) => { const m = trigger.match(new RegExp(`${n}="([^"]*)"`)); return m?.[1] ?? null; };
    })() });
    assert.equal(ctx.kind, 'browser');
    assert.deepEqual(Array.from(Menu.itemsFor({ ...ctx, groupable: true }), (i: { id: string }) => i.id), ['popout', 'rename', 'pin', 'move-to-group', 'close']);
    const session = Menu.itemsFor({ name: 'cloude_x', kind: 'session', groupable: true, renameable: true, restartable: true }).map((i: { id: string }) => i.id);
    assert.ok(session.includes('pin'), 'a session row menu always offers pin');
    assert.ok(session.includes('fork') && session.includes('mute'));
    assert.ok(Menu.uniqueShortcuts({ ...ctx, groupable: true }));
});

it('a browser row files itself with "add to" on a, and a layout row keeps "add" (members, +) beside it (#1785)', async () => {
    const browser = Menu.itemsFor({ name: 'browser:0123456789abcdef', kind: 'browser', groupable: true });
    const filing = browser.find((i: { id: string }) => i.id === 'move-to-group');
    assert.equal(filing!.label, 'add to');
    assert.equal(filing!.shortcut, 'a');
    const layout = Menu.itemsFor({ name: 'layout:1', kind: 'layout', groupable: true });
    const byId = (id: string) => layout.find((i: { id: string }) => i.id === id)!;
    assert.equal(byId('add-members').label, 'add');
    assert.equal(byId('add-members').shortcut, '+');
    assert.equal(byId('move-to-group').shortcut, 'a');
    assert.ok(Menu.uniqueShortcuts({ name: 'layout:1', kind: 'layout', groupable: true }));
});


it('a shell row lands in TERMINALS and not in PROJECTS; an agent row in the same project is unaffected', async () => {
    const html = body(fixtureRows());
    const terminalsRows = namesInGroup(html, 'terminals');
    assert.deepEqual(terminalsRows.sort(), ['cloude_console_home', 'cloude_myapp_shell'].sort());

    const projectRows = namesInGroup(html, 'p:10');
    assert.deepEqual(projectRows, ['cloude_myapp'], 'the shell row bound to the same project must not also appear under it');

    assert.ok(!html.includes('data-group="p:30"'));
    assert.ok(!html.includes('console-abc123'));
});

it('the folder subtitle draws for a terminal row and never for an agent row', async () => {
    const html = body(fixtureRows());
    assert.ok(html.includes('session-sidebar-row-subtitle'));
    assert.match(html, /data-name="cloude_myapp_shell"[\s\S]*?session-sidebar-row-subtitle[^>]*>\/Users\/example\/dev\/myapp</);
    assert.match(html, /data-name="cloude_console_home"[\s\S]*?session-sidebar-row-subtitle[^>]*>~</);
});

it('with no terminal rows at all, TERMINALS still draws its heading and a quiet empty line', async () => {
    const html = body([fixtureRows()[0]!]);
    assert.ok(html.includes('data-group="terminals"'));
    assert.match(html, /session-sidebar-company__empty[^>]*>no terminals open</);
});



it('a pinned shell row is duplicated into PINNED AND still renders under TERMINALS', async () => {
    const html = body(fixtureRows());
    assert.ok(html.includes('data-group="pinned"'));
    const pinnedNames = namesInGroup(html, 'pinned');
    assert.deepEqual(pinnedNames, ['cloude_console_home']);
    assert.equal((html.match(/data-name="cloude_console_home"/g) || []).length, 2);
    assert.ok(namesInGroup(html, 'terminals').includes('cloude_console_home'));
});

it('an unpinned shell row draws only once, under TERMINALS', async () => {
    const html = body(fixtureRows());
    assert.equal((html.match(/data-name="cloude_myapp_shell"/g) || []).length, 1);
});



it('folding TERMINALS collapses its body and survives being asked again (a repaint)', async () => {
    const arrangement = { collapsed: ['terminals'] };
    const first = body(fixtureRows(), arrangement);
    const second = body(fixtureRows(), arrangement);
    for (const html of [first, second]) {
        assert.ok(html.includes('data-group="terminals"'), 'the header still renders while folded');
        assert.ok(html.includes('data-collapsed="1"'));
        assert.equal(namesInGroup(html, 'terminals').length, 0, 'a folded section draws no rows');
    }
});

it('an unfolded TERMINALS renders its rows, and folding is independent of PROJECTS', async () => {
    const html = body(fixtureRows(), { collapsed: [] });
    assert.ok(html.includes('data-collapsed="0"'));
    assert.equal(namesInGroup(html, 'terminals').length, 2);
});



it('a query lists the matching terminal under AGENTS, and drops TERMINALS entirely when nothing matches', async () => {
    const normalize = Search.normalize;
    const matched = body(fixtureRows(), null, { query: normalize('myapp_shell') });
    assert.deepEqual(namesInGroup(matched, 'search:agents'), ['cloude_myapp_shell']);
    assert.ok(!matched.includes('data-group="terminals"'));
    const none = body(fixtureRows(), null, { query: normalize('zzz-nothing-zzz') });
    assert.ok(!none.includes('data-group="terminals"'));
});

