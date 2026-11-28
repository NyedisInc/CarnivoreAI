/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; method: string }[] = [];
let answer: { known: boolean; leftovers: unknown[] } = { known: true, leftovers: [] };
let confirmed = true;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    calls.push({ path, method });
    if (method === 'DELETE') {
      answer = { known: true, leftovers: (answer.leftovers as { install_id: string }[]).filter((x) => path !== `/pack/leftovers/${x.install_id}`) };
      return { forgotten: true };
    }
    return structuredClone(answer);
  },
}));
vi.mock('../modal', () => ({ openModal: vi.fn(async () => (confirmed ? true : null)) }));

import { setLocale } from '../i18n/index.svelte';
import { openModal } from '../modal';
import LeftoverStats from './LeftoverStats.svelte';

setLocale('en');
const NOW = Date.parse('2026-11-23T12:00:00Z');
const old = (id: string, name: string, rows: number) => ({ install_id: id, name, newest_at: NOW / 1000 - 3 * 86400, rows: { usage: rows, counters: 1, projects: 0, groups: 0 } });
const mounted: ReturnType<typeof mount>[] = [];

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
  flushSync();
}
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(LeftoverStats, { target, props: { nowMs: NOW } }));
  await settle();
  return target;
}

beforeEach(() => { calls.length = 0; confirmed = true; vi.mocked(openModal).mockClear(); });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

describe('old stats section', () => {
  test('is absent when there are none', async () => {
    answer = { known: true, leftovers: [] };
    const root = await render();
    expect(calls).toEqual([{ path: '/pack/leftovers', method: 'GET' }]);
    expect(root.querySelector('[data-sec="leftovers"]')).toBeNull();
  });

  test('lists each leftover with name, last seen and row count', async () => {
    answer = { known: true, leftovers: [old('iid-a', 'old mac', 12), old('iid-b', 'iid-b', 4)] };
    const root = await render();
    const rows = [...root.querySelectorAll('[data-leftover]')].map((r) => r.textContent?.replace(/\s+/g, ' ').trim());
    expect(rows).toEqual(['old mac last seen 3 days ago 13 rows delete', 'iid-b last seen 3 days ago 5 rows delete']);
  });

  test('the delete asks, then calls the route for that computer only and reads again', async () => {
    answer = { known: true, leftovers: [old('iid-a', 'old mac', 12), old('iid-b', 'other', 4)] };
    const root = await render();
    root.querySelector<HTMLButtonElement>('[data-leftover="iid-b"] [data-act="delete-leftover"]')!.click();
    await settle();
    expect(openModal).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([{ path: '/pack/leftovers/iid-b', method: 'DELETE' }]);
    expect([...root.querySelectorAll('[data-leftover]')].map((r) => r.getAttribute('data-leftover'))).toEqual(['iid-a']);
  });

  test('a declined confirm deletes nothing', async () => {
    answer = { known: true, leftovers: [old('iid-a', 'old mac', 12)] };
    confirmed = false;
    const root = await render();
    root.querySelector<HTMLButtonElement>('[data-act="delete-leftover"]')!.click();
    await settle();
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  });
});
