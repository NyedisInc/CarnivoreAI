import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { ItemMenuType } from '../item-menu/types';
const filedUnder = new Map<string, number | null>();
const calls: string[] = [];

vi.mock('../item-menu/open.svelte', () => ({ openItemMenu: () => true, closeItemMenu: () => {} }));
vi.mock('../add-to-menu/host', () => ({ addToMenuBridge: { openForProject: () => { calls.push('flyout'); } }, addToNodes: { forProject: () => [], forGroup: () => [] } }));
vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [], companyOf: (id: string) => filedUnder.get(id) ?? null }),
}));
vi.mock('../companies', () => ({
    companyById: (id: number) => (id === 7 ? { id: 7, name: 'acme', project_count: 2 } : undefined),
    setProjectCompany: vi.fn(async () => ({})),
    unassignProjectCompany: vi.fn(async (name: string) => { calls.push(`unassign ${name}`); return {}; }),
    createCompany: vi.fn(),
    renameCompany: vi.fn(async () => { throw Object.assign(new Error('dup'), { status: 409 }); }),
    deleteCompany: vi.fn(async () => { calls.push('delete'); return { deleted: true, orphaned: 2 }; }),
}));
vi.mock('./interaction-globals', () => ({
    announce: (text: string) => { calls.push(`say ${text}`); },
    announceFailure: (text: string) => { calls.push(`fail ${text}`); },
    hg: () => ({
        SessionSidebar: { _rows: [{ name: 'a', kind: 'agent', project_id: 5, project_name: 'proj' }] },
        App: { showConfirmModal: vi.fn(async (...args: unknown[]) => { calls.push(`confirm ${String(args[2])} ${String(args[5])}`); return true; }) },
        TextPromptModal: undefined,
    }),
    reasonOf: (e: unknown) => String((e as Error).message),
    refetchDrawer: async () => {},
    usableGroups: () => null,
    repaintDrawerRows: () => {},
}));

async function nodesOf(type: Extract<ItemMenuType, 'company' | 'project'>, key: string): Promise<MenuNode[] | null> {
    await import('../item-menu/menus/all');
    const { itemMenu } = await import('../item-menu/registry');
    return itemMenu(type, { key, anchor: {} as Element }, { close: () => {}, glyph: (icon) => icon ?? '' })?.nodes ?? null;
}

/**
 * The item menu's module graph is large and first imported by whichever test builds a menu, so on a loaded machine that cold import
 * ate the first test's own 5 s budget and failed it in a whole-directory run while it passed alone. Loaded here, under the hook's
 * longer timeout, no test pays for it.
 */
beforeAll(async () => {
    await import('../item-menu/menus/all');
    await import('../item-menu/registry');
}, 60_000);

beforeEach(() => {
    calls.length = 0;
    filedUnder.clear();
    (globalThis as { TextPromptModal?: unknown }).TextPromptModal = undefined;
});

describe('a company heading kebab', () => {
    it('offers rename, the shared color row and delete, and nothing for an unknown company', async () => {
        expect(await nodesOf('company', 'c:99')).toBeNull();
        const nodes = (await nodesOf('company', 'c:7'))!;
        expect(nodes.map((e) => e.glyphHtml)).toEqual(['rename', undefined, 'close']);
        expect(nodes.map((e) => !!e.sep), 'delete sits alone behind a hairline').toEqual([false, false, true]);
        expect(nodes.at(-1)!.danger).toBe(true);
        expect(nodes.filter((e) => e.swatches)).toHaveLength(1);
    });

    it('delete confirms with the destructive style and says the projects become orphaned', async () => {
        (await nodesOf('company', 'c:7'))!.find((e) => e.id === 'delete-company')!.run!();
        await vi.waitFor(() => expect(calls).toContain('delete'));
        expect(calls.some((c) => c.startsWith('confirm') && c.endsWith('danger') && c.includes('orphaned'))).toBe(true);
    });
});

describe('a project heading kebab', () => {
    it('has add to as a branch, and remove from company only when the project is filed', async () => {
        const bare = (await nodesOf('project', 'p:5'))!;
        expect(bare.find((e) => e.children)?.label).toBe('add to');
        expect(bare.some((e) => e.label === 'remove from company')).toBe(false);
        filedUnder.set('5', 7);
        const filed = (await nodesOf('project', 'p:5'))!;
        expect(filed.some((e) => e.label === 'remove from company')).toBe(true);
        filed.find((e) => e.label === 'remove from company')!.run!();
        await vi.waitFor(() => expect(calls).toContain('unassign proj'));
    });
});

describe('company writes', () => {
    it('a duplicate name (409) says a company with that name already exists', async () => {
        const { companyFailure } = await import('./company-actions');
        expect(companyFailure(Object.assign(new Error('x'), { status: 409 }), 'rename'))
            .toBe('a company with that name already exists');
        expect(companyFailure(new Error('boom'), 'rename')).toContain('boom');
    });

    it('a rename the server refuses as a duplicate shows that sentence', async () => {
        const { renameCompanyPrompt } = await import('./company-actions');
        (globalThis as { TextPromptModal?: unknown }).TextPromptModal = { open: async () => 'taken' };
        expect(await renameCompanyPrompt({ id: 7, name: 'acme', project_count: 2 })).toBe(false);
        expect(calls).toContain('fail a company with that name already exists');
    });
});
