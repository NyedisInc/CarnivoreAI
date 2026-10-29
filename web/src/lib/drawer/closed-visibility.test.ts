/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import { setDrawerController } from './controller-ref';
import { closedShown, init, setClosedShown } from './closed-visibility.svelte';
import { load } from './fetch';
import { current, save } from './store';

function bridge(store: Record<string, unknown>, writes: Array<[string, unknown]>) {
    return {
        PreferenceBridge: {
            read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
            write: vi.fn(async (field: string, value: unknown, local: () => void) => { writes.push([field, value]); store[field] = value; local(); }),
        },
    };
}

beforeEach(() => { localStorage.clear(); setDrawerEnv(null); setViewClassSource(() => 'desktop'); init(); });
afterEach(() => {
    setViewClassSource(null); setDrawerEnv(null); setDrawerController(null); vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).API;
});

it('is hidden when never chosen (Alex (Example-owner), 2026-10-18: off by default), and reading writes nothing', () => {
    const writes: Array<[string, unknown]> = [];
    setDrawerEnv(bridge({}, writes));
    init();
    expect(closedShown()).toBe(false);
    expect(writes).toEqual([]);
});

it('writes the desktop field, then the phone field, and the phone inherits until it chooses', async () => {
    const writes: Array<[string, unknown]> = [];
    const refreshNow = vi.fn();
    setDrawerController({ refreshNow } as never);
    const store: Record<string, unknown> = {};
    setDrawerEnv(bridge(store, writes));
    expect(setClosedShown(true)).toBe(true);
    expect(setClosedShown(true)).toBe(false);
    expect(refreshNow).toHaveBeenCalledTimes(1);
    setViewClassSource(() => 'mobile');
    init();
    expect(closedShown()).toBe(true);
    expect(setClosedShown(false)).toBe(true);
    await Promise.resolve();
    expect(writes).toEqual([['sidebar_show_closed', true], ['sidebar_show_closed_mobile', false]]);
    setViewClassSource(() => 'desktop');
    init();
    expect(closedShown()).toBe(true);
});

const live = { tmux_session: 'cloude_live', agent_family: 'claude', session: { id: 'ses_live', working_dir: '/x' } };
const rec = (over: Record<string, unknown>) => ({ agent_family: 'claude', project_id: 1, project_name: 'p', working_dir: '/x', ...over });
const records = [
    rec({ session_uuid: 'u-nap', tmux_name: 'carnivore_nap', asleep: true, lifecycle: 'asleep' }),
    rec({ session_uuid: 'u-shut', tmux_name: 'carnivore_shut', closed: true, lifecycle: 'stopped' }),
];

it('lists closed rows only while the toggle is on, and a closed row\'s pin stays either way', async () => {
    (globalThis as Record<string, unknown>).API = {
        listAttachableSessions: async () => [], listSessions: async () => [live],
        listSessionRecords: async () => records, listSessionCompanions: async () => [],
    };
    save(['carnivore_shut'], []);
    setClosedShown(true);
    expect((await load(null)).rows.map((r) => r.name).sort()).toEqual(['carnivore_nap', 'carnivore_shut', 'cloude_live']);
    setClosedShown(false);
    const off = await load(null);
    expect(off.rows.map((r) => r.name).sort()).toEqual(['carnivore_nap', 'cloude_live']);
    expect(current().pinned).toContain('carnivore_shut');
});
