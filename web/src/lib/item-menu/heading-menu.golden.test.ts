/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { goldenOfNodes, type GoldenEntry } from './golden-normalize';

const GOLDEN = path.join(__dirname, '__goldens__', 'heading-menus.json');

const filedUnder = new Map<string, number | null>();

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
        SessionSidebar: { _rows: [
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

beforeEach(() => {
    filedUnder.clear();
});

interface HeadingGolden { ariaLabel: string; entries: GoldenEntry[] }

async function headingMenuOf(kind: 'project' | 'company' | 'group' | 'color-group' | 'color-layout' | 'leader', key: string): Promise<HeadingGolden> {
    await import('./menus/all');
    const { itemMenu } = await import('./registry');
    const anchor = document.createElement('button');
    const env = { close: () => {}, glyph: () => '' };
    const built = kind === 'leader' ? itemMenu('leader', { ghost: { agentId: 1, name: key, rank: key === 'Alpha' ? 'alpha' : 'company' } as never, anchor }, env)
        : kind === 'color-group' ? itemMenu('color', { kind: 'group', id: key, anchor }, env)
            : kind === 'color-layout' ? itemMenu('color', { kind: 'layout', id: key, anchor }, env)
                : itemMenu(kind, { key, anchor }, env);
    return { ariaLabel: built!.ariaLabel, entries: goldenOfNodes(built!.nodes) };
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
        now['color group'] = await headingMenuOf('color-group', 'g-1');
        now['color layout'] = await headingMenuOf('color-layout', 'l-1');
        now['leader alpha'] = await headingMenuOf('leader', 'Alpha');
        now['leader company'] = await headingMenuOf('leader', 'Acme HQ');
        if (process.env.RECORD_GOLDENS === '1') fs.writeFileSync(GOLDEN, `${JSON.stringify(now, null, 2)}\n`);
        const golden = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as Record<string, HeadingGolden>;
        expect(Object.keys(now)).toEqual(Object.keys(golden));
        for (const name of Object.keys(golden)) expect(now[name], name).toEqual(golden[name]);
    });
});
