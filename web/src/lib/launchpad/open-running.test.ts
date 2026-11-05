/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeAll, expect, it, vi } from 'vitest';
import { currentNav, keepNav } from './nav-generation';
import { openRunning } from './open-running';
import { returnToActiveSession } from './navigation';
import type { NavHost } from './nav-host';

beforeAll(() => {
  const src = readFileSync(resolve(__dirname, '../../../../client/js/navigation-generation.js'), 'utf8');
  new Function('window', src).call(window, window);
});

it('the token read right after the call is the navigation the flow completes under, on a cold store', async () => {
  const rows: Array<{ session_id: string; is_active: boolean }> = [];
  let loaded!: () => void;
  const load = vi.fn(() => new Promise<void>((r) => { loaded = () => { rows.push({ session_id: 'ses_a', is_active: true }); r(); }; }));
  const entered = vi.fn();
  const host = {
    prepareTerminal: async () => ({ cols: 80, rows: 24 }),
    getSession: async () => ({ session: { id: 'ses_a' } }),
    returnToExistingTerminal: entered,
  } as unknown as NavHost;
  const done = openRunning('ses_a', 'carnivore_a', {
    rows: () => rows,
    load,
    rejoin: (id, nav) => returnToActiveSession(id, host, ((k: string) => k) as never, nav),
    attach: async () => {},
  });
  const claimed = currentNav();
  loaded();
  await done;
  expect(entered).toHaveBeenCalledTimes(1);
  expect(keepNav(claimed, 'test')).toBe(true);
});
