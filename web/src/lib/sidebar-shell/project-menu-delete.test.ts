/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';

const state = vi.hoisted(() => ({
    deleted: [] as string[],
    failDelete: '' as string,
    refetched: 0,
    projectsRefreshed: 0,
    failures: [] as string[],
    announced: [] as string[],
    rows: [] as Array<Record<string, unknown>>,
}));

vi.mock('../../opscenter/api/projects.svelte', () => ({
    projects: {
        status: 'ok',
        data: [],
        refresh: async () => { state.projectsRefreshed += 1; },
    },
}));

vi.mock('../projects-shared/history-api', () => ({
    historyApi: {
        list: async () => ({ state: 'ok', total: 0, offset: 0, limit: 50, next_offset: null, groups: [], facets: { agents: [], states: {} } }),
        confirm: async () => true,
        deleteProject: async (name: string) => {
            if (state.failDelete) throw new Error(state.failDelete);
            state.deleted.push(name);
            return { message: 'ok' };
        },
    },
}));

vi.mock('./interaction-globals', () => ({
    announce: (msg: string) => state.announced.push(msg),
    announceFailure: (msg: string) => state.failures.push(msg),
    hg: () => ({ SessionSidebar: { rows: () => state.rows } }),
    reasonOf: String,
    refetchDrawer: async () => { state.refetched += 1; },
    usableGroups: () => null,
    repaintDrawerRows: () => {},
}));

vi.mock('./company-actions', () => ({ fileProject: () => {}, newCompanyPrompt: () => {}, removeFromCompany: () => {} }));
vi.mock('./heading-project-actions', async (orig) => ({
    ...(await orig<typeof import('./heading-project-actions')>()),
    archiveProject: () => {}, newAgentInProject: () => {}, renameProject: () => {}, showProjectPath: () => {}, sleepProject: () => {},
}));

import { runDrawerProjectVerb } from './project-menu-run.svelte';

describe('drawer project kebab delete (#3358)', () => {
    beforeEach(() => {
        state.deleted = [];
        state.failDelete = '';
        state.refetched = 0;
        state.projectsRefreshed = 0;
        state.failures = [];
        state.announced = [];
        state.rows = [
            { name: 'carnivore_alpha', kind: 'agent', project_id: 115, project_name: 'alpha.project' },
            { name: 'carnivore_demo-shell', agent_family: 'shell', project_id: 107, project_name: 'demo-shell' },
        ];
    });

    it('falls back to projectNameFor when projects.data misses the id, deletes, and refreshes the drawer', async () => {
        runDrawerProjectVerb('p:115', 'delete-project');
        await vi.waitFor(() => expect(state.deleted).toEqual(['alpha.project']));
        await vi.waitFor(() => expect(state.refetched).toBeGreaterThanOrEqual(1));
        expect(state.projectsRefreshed).toBeGreaterThanOrEqual(1);
        expect(state.failures).toEqual([]);
    });

    it('deletes a terminal-only archived project whose only drawer row is a live shell (#3023, #3358)', async () => {
        runDrawerProjectVerb('p:107', 'delete-project');
        await vi.waitFor(() => expect(state.deleted).toEqual(['demo-shell']));
        await vi.waitFor(() => expect(state.refetched).toBeGreaterThanOrEqual(1));
        expect(state.projectsRefreshed).toBeGreaterThanOrEqual(1);
        expect(state.failures).toEqual([]);
    });

    it('surfaces delete refusals via announceFailure instead of only the screen-reader region', async () => {
        state.failDelete = 'swarm_refused: agent waking';
        runDrawerProjectVerb('p:115', 'delete-project');
        await vi.waitFor(() => expect(state.refetched).toBeGreaterThanOrEqual(1));
        flushSync();
        expect(state.failures).toContain('swarm_refused: agent waking');
    });
});
