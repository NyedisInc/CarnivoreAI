import { beforeEach, expect, test, vi } from 'vitest';

const stub = vi.hoisted(() => ({ listFeed: vi.fn(), getRun: vi.fn() }));
vi.mock('./api', () => stub);

import { feed, loadFeed, loadOlder, refreshFeed } from './feed-store.svelte';

type Page = { runs: { run_id: string; status: string; has_report: boolean }[]; total: number; next_before: string | null };

function page(ids: string[], total: number, next: string | null = null): Page {
  return { runs: ids.map((run_id) => ({ run_id, status: 'completed', has_report: false })), total, next_before: next };
}

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

beforeEach(() => {
  stub.listFeed.mockReset();
  feed.runs = [];
  feed.total = 0;
  feed.nextBefore = null;
  feed.status = 'idle';
  feed.loadingMore = false;
});

test('an older filter read landing last does not overwrite the newer one', async () => {
  const first = deferred<Page>();
  const second = deferred<Page>();
  stub.listFeed.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const a = loadFeed({ status: ['failed'] });
  const b = loadFeed({ status: ['completed'] });
  second.resolve(page(['new'], 1));
  await b;
  first.resolve(page(['old'], 9));
  await a;
  expect(feed.runs.map((r) => r.run_id)).toEqual(['new']);
  expect(feed.total).toBe(1);
});

test('a load older page for an old filter is discarded after a filter change', async () => {
  stub.listFeed.mockResolvedValueOnce(page(['a'], 5, 'cur'));
  await loadFeed({});
  const older = deferred<Page>();
  stub.listFeed.mockReturnValueOnce(older.promise);
  const more = loadOlder({});
  stub.listFeed.mockResolvedValueOnce(page(['z'], 1));
  await loadFeed({ status: ['failed'] });
  older.resolve(page(['stale'], 5));
  await more;
  expect(feed.runs.map((r) => r.run_id)).toEqual(['z']);
});

test('a push refresh captured before a filter change does not merge into the new list', async () => {
  stub.listFeed.mockResolvedValueOnce(page(['a'], 1));
  await loadFeed({});
  const late = deferred<Page>();
  stub.listFeed.mockReturnValueOnce(late.promise);
  const refresh = refreshFeed({});
  stub.listFeed.mockResolvedValueOnce(page(['z'], 1));
  await loadFeed({ status: ['failed'] });
  late.resolve(page(['a', 'b'], 2));
  await refresh;
  expect(feed.runs.map((r) => r.run_id)).toEqual(['z']);
});

test('the report cache is bounded and released when the page closes (u129-09)', async () => {
  const { reports, trimReports, releaseFeedCaches } = await import('./feed-store.svelte');
  for (let i = 0; i < 700; i++) reports[`old${i}`] = { state: 'ready', report: null };
  trimReports();
  expect(Object.keys(reports).length).toBe(600);
  expect(reports['old0']).toBeUndefined();
  feed.runs = [{ run_id: 'x' } as never];
  releaseFeedCaches();
  expect(Object.keys(reports).length).toBe(0);
  expect(feed.runs).toEqual([]);
  expect(feed.status).toBe('idle');
});
