/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    calls.push(path);
    return {
      cpu_percent: 23.4, cpu_count: 10, memory_percent: 92, memory_used_bytes: 21_400_000_000, memory_total_bytes: 34_400_000_000,
      disk_percent: null, disk_free_bytes: null, disk_total_bytes: null, load_1: 2.41, load_5: 1.87, load_15: 1.52, uptime_seconds: 273600,
    };
  },
}));

import Cell from './Cell.svelte';
import { readings, toneOf } from './meta';
import { machineStats } from './store.svelte';
import { META } from '../../engine/meta';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');
const apps: ReturnType<typeof mount>[] = [];
afterEach(() => { for (const app of apps.splice(0)) unmount(app); calls.length = 0; });

async function draw(width: number, height = 95): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  apps.push(mount(Cell, { target, props: { width, height, meta: META['machine-stats'], instance: 'x' } }));
  await tick(); await new Promise((r) => setTimeout(r, 0)); flushSync();
  return target;
}

describe('machine stats cell', () => {
  test('readings: unmeasured is words, tones turn at 75 and 90', () => {
    const list = readings({
      cpu_percent: 23.4, cpu_count: 10, memory_percent: 92, memory_used_bytes: 21_400_000_000, memory_total_bytes: 34_400_000_000,
      disk_percent: null, disk_free_bytes: null, disk_total_bytes: null, load_1: 2.41, load_5: 1.87, load_15: 1.52, uptime_seconds: 273600,
    });
    expect(list.map((r) => r.figure)).toEqual(['23%', '92%', 'not measured', '2.41', '3d 4h']);
    expect(list[1]!.sub).toBe('21.4 gb of 34.4 gb');
    expect([toneOf(74), toneOf(75), toneOf(90)]).toEqual(['ok', 'warn', 'hot']);
  });

  test('2 x 2 draws three meters and 8 x 2 five; the store exists only while mounted', async () => {
    expect(machineStats.current).toBeNull();
    const small = await draw(190);
    expect(small.querySelectorAll('[data-meter]').length).toBe(3);
    expect(calls).toEqual(['/machine-stats']);
    expect(small.querySelector('[data-meter="memory"] .oc-ms-fill--hot')).not.toBeNull();
    const wide = await draw(766);
    expect(wide.querySelectorAll('[data-meter]').length).toBe(5);
    for (const app of apps.splice(0)) unmount(app);
    expect(machineStats.current).toBeNull();
  });

  test('a stacked box with height to spare gives every bar meter its detail line below the bar', async () => {
    const tall = await draw(190, 220);
    expect(tall.querySelector('.oc-ms--tall')).not.toBeNull();
    for (const key of ['cpu', 'memory']) {
      expect(tall.querySelector(`[data-meter="${key}"] .oc-ms-sub--below`)).not.toBeNull();
    }
    const short = await draw(190, 95);
    expect(short.querySelector('.oc-ms-sub--below')).toBeNull();
  });
});
