/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import { init, setStatsShown, statsShown } from './stats-visibility.svelte';

afterEach(() => { setViewClassSource(null); setDrawerEnv(null); });
beforeEach(() => { localStorage.clear(); setViewClassSource(() => 'desktop'); });

it('writes the desktop field, then the phone field, and the phone inherits until it chooses', async () => {
    const writes: Array<[string, unknown]> = [];
    const store: Record<string, unknown> = {};
    setDrawerEnv({
        PreferenceBridge: {
            read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
            write: vi.fn(async (field: string, value: unknown, local: () => void) => { writes.push([field, value]); store[field] = value; local(); }),
        },
    });
    init();
    expect(statsShown()).toBe(false);
    expect(setStatsShown(true)).toBe(true);
    expect(setStatsShown(true)).toBe(false);
    setViewClassSource(() => 'mobile');
    init();
    expect(statsShown()).toBe(true);
    setStatsShown(false);
    await Promise.resolve();
    expect(writes).toEqual([['sidebar_show_stats', true], ['sidebar_show_stats_mobile', false]]);
});
