import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { assignMenuKeys, registeredKey } from '../menu-keys/menu-keys';

const filedUnder = new Map<string, number | null>();

vi.mock('../item-menu/open.svelte', () => ({ openItemMenu: () => true, closeItemMenu: () => {} }));
vi.mock('../add-to-menu/host', () => ({ addToMenuBridge: { openForProject: () => {} }, addToNodes: { forProject: () => [], forGroup: () => [] } }));
vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [], companyOf: (id: string) => filedUnder.get(id) ?? null }),
}));
vi.mock('../companies', () => ({
    companyById: (id: number) => (id === 7 ? { id: 7, name: 'acme', project_count: 2 } : undefined),
}));
vi.mock('../i18n/index.svelte', () => ({ t: (k: string) => k }));
vi.mock('../../cplugs/huddle/chat/chat-api', () => ({ wakeAgent: vi.fn(), renameAgent: vi.fn(), turnOffAgent: vi.fn() }));
vi.mock('../../cplugs/huddle/agents/agent-roster.svelte', () => ({ refreshRoster: async () => {} }));
vi.mock('../leader-confirm/confirm', () => ({ askLeaderConfirm: vi.fn() }));
vi.mock('../../cplugs/huddle/agents/agent-terminal', () => ({ openAgentTerminal: vi.fn() }));
vi.mock('./interaction-globals', () => ({
    announce: () => {},
    announceFailure: () => {},
    hg: () => ({
        SessionSidebar: { _rows: [{ name: 'a', kind: 'agent', project_id: 5, project_name: 'proj' }] },
        SessionRowMenuIcons: { svg: () => '' },
    }),
    reasonOf: (e: unknown) => String((e as Error).message),
    refetchDrawer: async () => {},
    usableGroups: () => ({
        groupByUuid: (u: string) => ({ group_uuid: u, name: 'crew', members: ['a'] }),
        current: () => ({ groups: [{ group_uuid: 'g0' }, { group_uuid: 'g1' }, { group_uuid: 'g2' }] }),
    }),
    repaintDrawerRows: () => {},
}));

beforeEach(() => { filedUnder.clear(); });

async function allMenus(): Promise<Record<string, MenuNode[]>> {
    await import('../item-menu/menus/all');
    const { itemMenu } = await import('../item-menu/registry');
    const env = { close: () => {}, glyph: () => '' };
    const anchor = {} as Element;
    const out: Record<string, MenuNode[]> = {};
    out['project'] = itemMenu('project', { key: 'p:5', anchor }, env)!.nodes;
    filedUnder.set('5', 7);
    out['project filed'] = itemMenu('project', { key: 'p:5', anchor }, env)!.nodes;
    out['group middle'] = itemMenu('group', { key: 'g1', anchor }, env)!.nodes;
    out['group first'] = itemMenu('group', { key: 'g0', anchor }, env)!.nodes;
    out['company'] = itemMenu('company', { key: 'c:7', anchor }, env)!.nodes;
    out['ghost'] = itemMenu('leader', { ghost: { agentId: 2, name: 'Acme HQ', rank: 'company' }, anchor }, env)!.nodes;
    return out;
}

describe('the sidebar heading menus draw the fixed map', () => {
    it('every entry is registered, drawn on exactly its registry letter, and no menu repeats a key', async () => {
        const menus = await allMenus();
        expect(Object.keys(menus).length, 'population: all six menus opened').toBe(6);
        for (const [name, entries] of Object.entries(menus)) {
            expect(entries.length, `${name}: has entries`).toBeGreaterThan(1);
            const items = entries.filter((e) => e.label).map((e) => ({ id: e.id, label: e.label }));
            const keys = assignMenuKeys(items);
            items.forEach((item, at) => {
                expect(registeredKey(item.id), `${name}: ${item.id} is in the fixed map`).not.toBeNull();
                expect(keys[at], `${name}: ${item.id} draws its registry letter`).toBe(registeredKey(item.id));
            });
            expect(new Set(keys).size, `${name}: no key repeats`).toBe(keys.length);
        }
    });

    it('one action id has one letter in every menu it appears in', async () => {
        const seen = new Map<string, string>();
        for (const entries of Object.values(await allMenus())) {
            const items = entries.filter((e) => e.label).map((e) => ({ id: e.id, label: e.label }));
            assignMenuKeys(items).forEach((key: string, at: number) => {
                const id = items[at]!.id!;
                expect(seen.get(id) ?? key, `${id} keeps one letter`).toBe(key);
                seen.set(id, key);
            });
        }
        expect(seen.get('sleep')).toBe('s');
        expect(seen.get('rename-project')).toBe('r');
        expect(seen.get('delete-company')).toBe('d');
    });
});
