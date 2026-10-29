/** @vitest-environment jsdom */
import { beforeEach, expect, test, vi } from 'vitest';

const stops: Array<ReturnType<typeof vi.fn>> = [];
const pushed: Array<() => void> = [];

vi.mock('../resource-push/boot', () => ({
    resourcePush: () => ({
        onChange: () => () => {},
        isLive: () => false,
        pushOrPoll: (refresh: () => void) => {
            const stop = vi.fn();
            stops.push(stop);
            pushed.push(refresh);
            return stop;
        },
    }),
}));
vi.mock('./pack-flow', () => ({ runPackFlow: async () => ({ started: true, notice: '' }) }));

import { ProjectsController } from './page-controller.svelte';
import type { HistoryApi } from './history-api';
import { group } from './test-fixtures';

function controller(state: { value: string }): { c: ProjectsController; reads: string[] } {
    const reads: string[] = [];
    const api = {
        list: async (query: string) => {
            reads.push(query);
            const g = group({ name: 'alpha' });
            return { state: 'ok', total: 1, offset: 0, limit: 50, next_offset: null, facets: { agents: [], states: {} }, groups: [{ ...g, project: { ...g.project!, storage: { state: state.value } } }] };
        },
        confirm: async () => true,
        pack: {},
    } as unknown as HistoryApi;
    return { c: new ProjectsController({ api, t: (k: string) => k, embedded: true, close: () => {} }), reads };
}

const flush = async (): Promise<void> => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };

beforeEach(() => {
    stops.length = 0;
    pushed.length = 0;
});

test('closing the page stops the follower', async () => {
    const { c } = controller({ value: 'packing' });
    c.applyRoute({ view: 'projects', company: null, project: 'alpha', session: null });
    await flush();
    c.projectAction('pack-folder', c.project ?? undefined);
    await flush();
    expect(stops).toHaveLength(1);
    c.stop();
    expect(stops[0]).toHaveBeenCalled();
});

test('a second press replaces the follower instead of starting a second one', async () => {
    const { c } = controller({ value: 'packing' });
    c.applyRoute({ view: 'projects', company: null, project: 'alpha', session: null });
    await flush();
    c.projectAction('pack-folder', c.project ?? undefined);
    await flush();
    c.projectAction('pack-folder', c.project ?? undefined);
    await flush();
    expect(stops).toHaveLength(2);
    expect(stops[0]).toHaveBeenCalled();
    expect(stops[1]).not.toHaveBeenCalled();
});

test('the follower ends from a fresh read of that project, even on a route that loaded another list', async () => {
    const state = { value: 'packing' };
    const { c, reads } = controller(state);
    c.applyRoute({ view: 'projects', company: null, project: 'alpha', session: null });
    await flush();
    c.projectAction('pack-folder', c.project ?? undefined);
    await flush();
    c.applyRoute({ view: 'projects', company: null, project: null, session: null });
    await flush();
    state.value = 'packed';
    reads.length = 0;
    pushed[0]!();
    await flush();
    expect(reads.length).toBeGreaterThan(0);
    expect(stops[0]).toHaveBeenCalled();
});
