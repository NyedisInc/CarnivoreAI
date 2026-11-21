/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async () => []) }));

import { authFetch } from '../../api/auth.svelte';
import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import type { SlotId } from '../../engine/types';

let handle: Record<string, unknown> | null = null;
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; });

test('a card still loading asks for the definitions itself', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.mocked(authFetch).mockImplementation((async (path: string) => (path === '/stats/settings' ? { enabled: true, revision: 1 } : [])) as never);
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 300, height: 260 } as never });
  for (let i = 0; i < 6; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  expect(vi.mocked(authFetch)).toHaveBeenCalledWith('/stats/charts');
  expect(analytics.loaded).toBe(true);
  expect(target.textContent).toContain('chart definition unavailable');
});
