import { beforeEach, expect, test, vi } from 'vitest';
import type { SessionInfo } from './types';
import {
  WOKEN_HOLD_MS, WOKEN_READ_DEADLINE_MS, findRow, holdWoken, mergeWoken, reachWoken, resetWokenForTests,
} from './woken-rows';

const row = (id: number, sesId = 'ses_a'): SessionInfo => ({ session_row_id: id, session: { id: sesId } }) as unknown as SessionInfo;

beforeEach(() => resetWokenForTests());

function clock() {
  let t = 1_000;
  return { now: () => t, sleep: async (ms: number) => { t += ms; } };
}

test('a live push that lacks the row is bypassed by a direct read, and the tab binds without the push', async () => {
  const c = clock();
  const found = await reachWoken(194, { pushed: () => [], readList: async () => [row(194)], ...c });
  expect(found?.session_row_id).toBe(194);
  expect(mergeWoken([], c.now()).map((r) => r.session_row_id)).toEqual([194]);
});

test('the late push reconciles: one row, the pushed one, and the hold is gone', () => {
  holdWoken(row(194, 'ses_held'), 1_000);
  const merged = mergeWoken([row(194, 'ses_pushed')], 2_000);
  expect(merged).toHaveLength(1);
  expect(merged[0]!.session.id).toBe('ses_pushed');
  expect(mergeWoken([], 3_000)).toHaveLength(0);
});

test('a hold older than the bound is dropped', () => {
  holdWoken(row(194), 1_000);
  expect(mergeWoken([], 1_000 + WOKEN_HOLD_MS + 1)).toHaveLength(0);
});

test('a row the list never carries gives null at the deadline and holds nothing', async () => {
  const c = clock();
  const warn = vi.fn();
  const read = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValue([]);
  vi.spyOn(console, 'warn').mockImplementation(warn);
  const found = await reachWoken(194, { pushed: () => null, readList: read, ...c });
  expect(found).toBeNull();
  expect(c.now()).toBeGreaterThan(1_000 + WOKEN_READ_DEADLINE_MS);
  expect(warn).toHaveBeenCalled();
  expect(mergeWoken([], c.now())).toHaveLength(0);
});

test('a pushed row is returned at once and holds nothing', async () => {
  const c = clock();
  const read = vi.fn();
  const found = await reachWoken(194, { pushed: () => [row(194)], readList: read, ...c });
  expect(found?.session_row_id).toBe(194);
  expect(read).not.toHaveBeenCalled();
  expect(mergeWoken([], c.now())).toHaveLength(0);
});

test('a row is found by the tab key or by session_uuid, on the wrapper only', () => {
  const rows = [{ session_row_id: 4, session_uuid: 'u4', session: { id: 'ses_4', session_uuid: 'u-nested' } }] as unknown as SessionInfo[];
  expect(findRow(rows, 4)?.session_uuid).toBe('u4');
  expect(findRow(rows, 'u4')?.session_row_id).toBe(4);
  expect(findRow(rows, 'u-nested')).toBeNull();
  expect(findRow(null, 'u4')).toBeNull();
});
