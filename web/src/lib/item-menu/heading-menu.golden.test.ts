/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { setCollapsedMany } from '../drawer/store';
import { goldenOfNodes, type GoldenEntry } from './golden-normalize';

const GOLDEN = path.join(__dirname, '__goldens__', 'heading-menus.json');

const filedUnder = new Map<string, number | null>();

const editor = vi.hoisted(() => ({ canEdit: false, active: false }));
vi.mock('../../opscenter/layout-editor/empty-space-menu.svelte', async (orig) => ({
    ...(await orig<typeof import('../../opscenter/layout-editor/empty-space-menu.svelte')>()), canOpen: () => editor.canEdit,
}));
vi.mock('../../opscenter/layout-editor/editor.svelte', async (orig) => ({
    ...(await orig<typeof import('../../opscenter/layout-editor/editor.svelte')>()), layoutEditor: { get active() { return editor.active; } },
}));

vi.mock('../add-to-menu/host', () => ({
    addToNodes: { forProject: () => [{ id: 'acme', label: 'acme', run: () => {} }], forGroup: () => [{ id: 'agents', label: 'agents', children: [] }] },
    addToMenuBridge: { close: () => {}, openForProject: () => {} },
    ADD_TO_CASCADE_CONTAINER_ID: 'x',
}));
vi.mock('../sidebar-shell/company-source.svelte', () => ({
    companySource: () => ({ companies: [], companyOf: (id: string) => filedUnder.get(id) ?? null, projectNameOf: () => null }),
}));
vi.mock('../companies', () => ({
    companyById: (id: number) => (id === 7 ? { id: 7, name: 'acme', project_count: 2, hue: 120 } : id === 8 ? { id: 8, name: 'plain', project_count: 0 } : undefined),
    setCompanyColor: vi.fn(async () => ({})),
    setProjectCompany: vi.fn(async () => ({})),
    unassignProjectCompany: vi.fn(async () => ({})),
    createCompany: vi.fn(),
    renameCompany: vi.fn(),
    deleteCompany: vi.fn(),
}));
vi.mock('../project-colors/store.svelte', () => ({ projectColorOf: (id: number | null) => (id === 5 ? '#4e69ba' : null) }));
const GROUPS = [
    { group_uuid: 'g-1', name: 'crew', members: [{}, {}], colour: '#6c799f' },
    { group_uuid: 'g-2', name: 'ops', members: [{}] },
    { group_uuid: 'g-3', name: 'misc', members: [] },
];
vi.mock('../sidebar-shell/interaction-globals', () => ({
    announce: () => {},
    announceFailure: () => {},
    hg: () => ({
        SessionSidebar: { rows() { return this._rows; }, _rows: [
            { name: 'a', kind: 'agent', project_id: 5, project_name: 'proj' },
            { name: 'b', kind: 'agent', project_id: 6, project_name: 'other' },
            { name: 'c', kind: 'agent', project_id: 9 },
        ] },
        SessionRowMenuIcons: undefined,
        CloudeWeb: { layouts: { get: (id: string) => (id === 'l-1' ? { name: 'deck', colour: '' } : undefined) } },
    }),
    reasonOf: (e: unknown) => String((e as Error).message),
    refetchDrawer: async () => {},
    refreshGroups: async () => {},
    applyGroups: () => {},
    usableGroups: () => ({ current: () => ({ groups: GROUPS }), groupByUuid: (u: string) => GROUPS.find((g) => g.group_uuid === u) }),
    repaintDrawerRows: () => {},
}));

const priorDrawer = (globalThis as { SessionSidebar?: unknown }).SessionSidebar;

beforeEach(() => {
    filedUnder.clear();
});

afterEach(() => {
    (globalThis as { SessionSidebar?: unknown }).SessionSidebar = priorDrawer;
    editor.canEdit = false;
    editor.active = false;
    setCollapsedMany([], ['terminals']);
});

interface HeadingGolden { ariaLabel: string; entries: GoldenEntry[] }

async function headingMenuOf(kind: 'project' | 'company' | 'group' | 'section' | 'color-group' | 'color-layout' | 'leader', key: string): Promise<HeadingGolden> {
    await import('./menus/all');
    const { itemMenu } = await import('./registry');
    const anchor = document.createElement('button');
    const env = { close: () => {}, glyph: () => '' };
    const built = kind === 'leader' ? itemMenu('leader', { ghost: { agentId: 1, name: key, rank: key === 'Alpha' ? 'alpha' : 'company' } as never, anchor }, env)
        : kind === 'color-group' ? itemMenu('color', { kind: 'group', id: key, anchor }, env)
            : kind === 'color-layout' ? itemMenu('color', { kind: 'layout', id: key, anchor }, env)
                : itemMenu(kind, { key, anchor: kind === 'section' ? sectionRow(key) : anchor }, env);
    return { ariaLabel: built!.ariaLabel, entries: goldenOfNodes(built!.nodes) };
}

function sectionRow(key: string): Element {
    const list = document.createElement('div');
    list.innerHTML = ['pinned', 'terminals', 'browsers'].map((id) => `<div data-section="${id}"><div class="session-sidebar-group__headerrow"><button data-group-toggle="${id}" aria-expanded="${id === 'terminals' ? 'false' : 'true'}"><span class="session-sidebar-group__label">${id}</span></button></div></div>`).join('');
    (globalThis as { SessionSidebar?: unknown }).SessionSidebar = { listEl: list };
    return list.querySelector(`[data-group-toggle="${key}"]`)!.parentElement!;
}

describe('the heading menus golden', () => {
    test('every heading kind in every representative state offers exactly the recorded menu', async () => {
        const now: Record<string, HeadingGolden> = {};
        now['project unfiled'] = await headingMenuOf('project', 'p:5');
        filedUnder.set('5', 7);
        now['project filed'] = await headingMenuOf('project', 'p:5');
        now['project unnamed'] = await headingMenuOf('project', 'p:9');
        now['company with color'] = await headingMenuOf('company', 'c:7');
        now['company without color'] = await headingMenuOf('company', 'c:8');
        now['group first'] = await headingMenuOf('group', 'g-1');
        now['group middle'] = await headingMenuOf('group', 'g-2');
        now['group last'] = await headingMenuOf('group', 'g-3');
        now['section first, open'] = await headingMenuOf('section', 'pinned');
        setCollapsedMany(['terminals'], []);
        now['section middle, folded'] = await headingMenuOf('section', 'terminals');
        setCollapsedMany([], ['terminals']);
        now['section last, with new browser'] = await headingMenuOf('section', 'browsers');
        editor.canEdit = true;
        now['section middle, can edit layout'] = await headingMenuOf('section', 'terminals');
        editor.active = true;
        now['section middle, editing layout'] = await headingMenuOf('section', 'terminals');
        editor.canEdit = false;
        editor.active = false;
        now['color group'] = await headingMenuOf('color-group', 'g-1');
        now['color layout'] = await headingMenuOf('color-layout', 'l-1');
        now['leader alpha'] = await headingMenuOf('leader', 'Alpha');
        now['leader company'] = await headingMenuOf('leader', 'Acme HQ');
        if (process.env.RECORD_GOLDENS === '1') fs.writeFileSync(GOLDEN, `${JSON.stringify(now, null, 2)}\n`);
        const golden = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as Record<string, HeadingGolden>;
        expect(Object.keys(now)).toEqual(Object.keys(golden));
        for (const name of Object.keys(golden)) expect(now[name], name).toEqual(golden[name]);
    });

    test('the group menu folds its five top items into one customize branch', async () => {
        const menu = await headingMenuOf('group', 'g-2');
        const top = menu.entries.map((e) => e.id);
        expect(top.slice(0, 2)).toEqual(['customize', 'fold-inside']);
        const customize = menu.entries[0]!;
        expect((customize.children ?? []).map((e) => e.id)).toEqual(['rename-group', 'add-members', 'colour', 'group-icon', 'group-rule']);
        for (const id of ['rename-group', 'add-members', 'colour', 'group-icon', 'group-rule']) expect(top, id).not.toContain(id);
    });

    test('the group menu names its dynamic-group editor "filter", never "rule"', async () => {
        const menu = await headingMenuOf('group', 'g-1');
        const entry = JSON.stringify(menu).match(/\{[^{}]*"id":"group-rule"[^{}]*\}/);
        expect(entry?.[0]).toContain('"label":"filter"');
        expect(entry?.[0]).toContain('"key":"e"');
        expect(JSON.stringify(menu)).not.toContain('"label":"rule"');
    });
});
