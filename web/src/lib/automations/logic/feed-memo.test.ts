import { afterEach, expect, test, vi } from 'vitest';

const spy = vi.hoisted(() => ({ compare: 0 }));
vi.mock('./diff', async (orig) => {
  const real = await orig<typeof import('./diff')>();
  return { ...real, compare: (...args: Parameters<typeof real.compare>) => ((spy.compare += 1), real.compare(...args)) };
});

import { analyse, haystack, type FeedRow } from './feed';
import type { ReportSlot } from './types';

const row = (id: string, at: number): FeedRow =>
  ({ run_id: id, automation_id: 'a', status: 'succeeded', reason: null, has_report: true, slot_at: at, started_at: at, ended_at: at + 1, number: at, error: null, trigger: 'schedule', skip_count: null }) as unknown as FeedRow;

afterEach(() => (spy.compare = 0));

test('an unchanged pair is compared once across analyses', () => {
  const slots: Record<string, ReportSlot> = {
    r2: { state: 'ready', report: { count: 2, items: ['a'] } },
    r1: { state: 'ready', report: { count: 1, items: ['a'] } },
  };
  const lookup = (id: string): ReportSlot => slots[id] ?? { state: 'pending' };
  const runs = [row('r2', 2), row('r1', 1)];
  analyse(runs, [], lookup);
  analyse(runs, [], lookup);
  expect(spy.compare).toBe(1);
});

test('a search stringifies a report once', () => {
  const report = { big: 'x'.repeat(100) };
  const slot: ReportSlot = { state: 'ready', report };
  const stringify = vi.spyOn(JSON, 'stringify');
  const ctx = { clock: new Proxy({}, { get: () => () => '' }) as never, tz: 'UTC', now: 10 } as never;
  haystack(row('r1', 1), slot, ctx, 0);
  haystack(row('r1', 1), slot, ctx, 0);
  const onReport = stringify.mock.calls.filter((c) => c[0] === report).length;
  stringify.mockRestore();
  expect(onReport).toBe(1);
});
