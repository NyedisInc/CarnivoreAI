/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const listing = vi.hoisted(() => ({ data: [] as unknown[], status: 'ok', refresh: async () => undefined }));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));
const put = vi.hoisted(() => vi.fn());
vi.mock('./api', async (actual) => ({ ...(await actual<typeof import('./api')>()), putShape: put }));

import { ApiError } from '../api/auth.svelte';
import { terminalLayout } from '../engine/layout.svelte';
import { resetTabCache, setGroups } from '../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { flushShape, resetSaveTarget, startSaveTarget, whileApplying, type SaveHooks } from './save-target.svelte';
import { clearLayoutMode, layoutMode } from './mode.svelte';

const hooks = { landed: vi.fn(), deleted: vi.fn(), adopt: vi.fn(), missing: vi.fn(), announce: vi.fn() } satisfies SaveHooks;

function stale(revision: number): ApiError {
  const current = { layout_uuid: 'L1', revision, shape: { layout: null, groups: {} }, members: [] };
  return new ApiError('stale', 409, null, { detail: { code: 'layout_stale', detail: 'stale', current } });
}

function landed(revision: number) {
  return { layout: { layout_uuid: 'L1', revision, members: [], shape: {} }, deleted: false, survivor: null, created: false };
}

beforeEach(() => {
  vi.useFakeTimers();
  put.mockReset();
  Object.values(hooks).forEach((fn) => fn.mockReset());
  startSaveTarget(hooks);
  terminalLayout.bindKey('layout:L1', terminalLayout.snapshot());
  layoutMode.uuid = 'L1';
  layoutMode.revision = 3;
  layoutMode.anchorRowId = 1;
});

afterEach(() => {
  vi.useRealTimers();
  resetSaveTarget();
  clearLayoutMode();
  terminalLayout.bindSession('');
  resetTabCache();
  localStorage.clear();
});

async function change(): Promise<void> {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:2'] } });
  await vi.advanceTimersByTimeAsync(700);
}

test('a user change sends the whole shape, anchor row keyed, at the revision seen', async () => {
  put.mockResolvedValue(landed(4));
  await change();
  expect(put).toHaveBeenCalledTimes(1);
  const [uuid, shape, revision] = put.mock.calls[0]!;
  expect([uuid, revision]).toEqual(['L1', 3]);
  expect(shape.groups[PRIMARY_SLOT].tabs).toEqual(['terminal:row:1', 'terminal:row:2']);
  expect(layoutMode.revision).toBe(4);
});

test('a stale revision takes the server revision and replays the change once', async () => {
  put.mockRejectedValueOnce(stale(7)).mockResolvedValueOnce(landed(8));
  await change();
  expect(put).toHaveBeenCalledTimes(2);
  expect(put.mock.calls[1]![2]).toBe(7);
  expect(hooks.announce).toHaveBeenCalledWith('', 'merged');
  expect(hooks.adopt).not.toHaveBeenCalled();
});

test('a second 409 adopts the stored Layout and says the change was lost', async () => {
  put.mockRejectedValueOnce(stale(7)).mockRejectedValueOnce(stale(9));
  await change();
  expect(put).toHaveBeenCalledTimes(2);
  expect(hooks.adopt).toHaveBeenCalledTimes(1);
  expect(hooks.announce).toHaveBeenCalledWith('', 'lost');
});

test('a write that leaves one member hands the survivor over', async () => {
  const gone = { layout: null, deleted: true, survivor: { session_row_id: 1, session_uuid: 'u', position: 0 }, created: false };
  put.mockResolvedValue(gone);
  await change();
  expect(hooks.deleted).toHaveBeenCalledWith(gone);
});

test('a server shape being applied is never sent back', async () => {
  whileApplying(() => setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:5'] } }));
  await vi.advanceTimersByTimeAsync(700);
  await flushShape();
  expect(put).not.toHaveBeenCalled();
});

test('a change to a session key goes nowhere near the Layout route', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:2'] } });
  await vi.advanceTimersByTimeAsync(700);
  expect(put).not.toHaveBeenCalled();
});
