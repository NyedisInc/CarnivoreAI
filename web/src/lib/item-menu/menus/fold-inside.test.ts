/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';

const fold = vi.hoisted(() => vi.fn(() => true));
const folded = vi.hoisted(() => ({ now: false }));
vi.mock('../../sidebar-shell/heading-fold', () => ({ cascadeBandFold: fold, isBandFolded: () => folded.now }));
vi.mock('../../add-to-menu/host', () => ({ addToNodes: { forProject: () => [], forGroup: () => [] }, addToMenuBridge: {}, ADD_TO_CASCADE_CONTAINER_ID: 'x' }));
vi.mock('../../sidebar-shell/company-source.svelte', () => ({ companySource: () => ({ companyOf: () => null }) }));
vi.mock('../../companies', () => ({ companyById: (id: number) => (id === 7 ? { id: 7, name: 'acme', project_count: 1 } : undefined), setCompanyColor: vi.fn() }));
vi.mock('../../project-colors/store.svelte', () => ({ projectColorOf: () => null }));
const GROUPS = [{ group_uuid: 'g-1', name: 'crew', members: [] }];
vi.mock('../../sidebar-shell/interaction-globals', () => ({
    announce: () => {}, announceFailure: () => {}, reasonOf: String, refetchDrawer: async () => {}, repaintDrawerRows: () => {},
    hg: () => ({ SessionSidebar: { _rows: [{ name: 'a', kind: 'agent', project_id: 5, project_name: 'proj' }] } }),
    usableGroups: () => ({ current: () => ({ groups: GROUPS }), groupByUuid: (u: string) => GROUPS.find((g) => g.group_uuid === u) }),
}));

interface DrawnNode { id: string; label: string; run: () => void }

async function nodesOf(type: 'project' | 'company' | 'group', key: string): Promise<DrawnNode[]> {
    await import('../menus/all');
    const { itemMenu } = await import('../registry');
    const built = itemMenu(type, { key, anchor: document.createElement('button') }, { close: () => {}, glyph: () => '' });
    return built!.nodes as unknown as DrawnNode[];
}

describe('fold everything inside', () => {
    test.each([['project', 'p:5', 'p:5'], ['company', 'c:7', 'c:7'], ['group', 'g-1', 'g:g-1']] as const)(
        'the %s heading lists it and picking it folds band %s', async (type, key, band) => {
            fold.mockClear();
            const item = (await nodesOf(type, key)).find((n) => n.id === 'fold-inside');
            expect(item?.label).toBe('fold everything inside');
            item!.run();
            expect(fold).toHaveBeenCalledExactlyOnceWith(band);
        },
    );

    test('the entry reads unfold everything inside while the heading is folded', async () => {
        folded.now = true;
        try {
            const item = (await nodesOf('company', 'c:7')).find((n) => n.id === 'fold-inside');
            expect(item?.label).toBe('unfold everything inside');
        } finally {
            folded.now = false;
        }
    });

    test('the project heading archives on v', async () => {
        const nodes = await nodesOf('project', 'p:5');
        expect(nodes.some((n) => n.id === 'delete-project')).toBe(false);
        const archive = nodes.find((n) => n.id === 'archive-project');
        expect(archive?.label).toBe('archive project');
    });
});
