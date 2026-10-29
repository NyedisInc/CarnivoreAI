/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const folds = vi.hoisted(() => ({ collapsed: true }));
vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [], projectNameOf: (id: string) => (id === '12' ? 'hq' : null), companyOf: () => null }),
    watchCompanies: () => {},
}));
vi.mock('../drawer/store', () => ({
    isCollapsed: () => false, setCollapsedMany: () => {}, toggleCollapsed: () => folds.collapsed,
}));
vi.mock('../drawer/group-store', async () => {
    const real = await vi.importActual<typeof import('../drawer/group-store')>('../drawer/group-store');
    return { ...real, groupByUuid: (u: string) => (u === 'abc' ? { name: 'night shift' } : null), projectBandKeyFor: () => null };
});
import { toggleBandFold } from './heading-fold';
import { newAgentInProject } from './heading-project-actions';

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    Object.assign(globalThis, { SessionSidebar: { _rows: [], _fetchAndRender: async () => {} } });
});

const said = (): string => document.getElementById('session-sidebar-live')?.textContent ?? '';

describe('fold announcement names', () => {
    it.each([
        ['p:12', 'hq group collapsed'],
        ['g:abc', 'night shift group collapsed'],
        ['companies', 'companies group collapsed'],
        ['pinned', 'pinned group collapsed'],
        ['other', 'other group collapsed'],
        ['rogue', 'rogue agents group collapsed'],
        ['p:99', 'p:99 group collapsed'],
    ])('%s is announced as %s', (key, sentence) => {
        toggleBandFold(key);
        expect(said()).toBe(sentence);
    });
});

describe('new agent on an inactive project', () => {
    it('finds the project folder by the id in the band key when no row carries it', async () => {
        const selectProject = vi.fn(async () => {});
        const getProjects = vi.fn(async () => [{ id: 12, path: '/work/hq' }]);
        Object.assign(globalThis, { CloudeWeb: { launchpad: { selectProject } }, API: { getProjects } });
        await newAgentInProject('p:12');
        expect(selectProject).toHaveBeenCalledWith({ name: 'hq', path: '/work/hq' });
    });
});
