import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BATCH_LIMIT, COALESCE_MS, createQueryClient, type BatchItem, type ClientDeps } from './query-client';
import type { QueryBody } from '../cells/analytics/types';

const body = (metric: string, extra: Partial<QueryBody> = {}): QueryBody => ({
  metric, operation: 'timeline', from: '2026-09-01T00:00:00Z', to: '2026-09-02T00:00:00Z', timezone: 'UTC', resolution: 'auto', filters: {}, ...extra,
});
const ok = (metric: string): BatchItem => ({ ok: true, result: { metric, operation: 'timeline', unit: 'tokens', resolution: 'hour', series: [] } });

let hidden = false;
let visibleCb: (() => void) | null = null;
let posts: QueryBody[][] = [];
let respond: (items: QueryBody[], signal: AbortSignal) => Promise<BatchItem[]>;
const deps: ClientDeps = {
  post: (items, signal) => { posts.push(items); return respond(items, signal); },
  hidden: () => hidden,
  onVisible: (cb) => { visibleCb = cb; return () => { visibleCb = null; }; },
};

beforeEach(() => { vi.useFakeTimers(); hidden = false; visibleCb = null; posts = []; respond = async (items) => items.map((item) => ok(item.metric)); });
afterEach(() => vi.useRealTimers());

describe('query batch client', () => {
  test('widgets asking in one window leave as ONE request and each gets only its own results', async () => {
    const { runQueries } = createQueryClient(deps);
    const a = runQueries([body('a1'), body('a2')]);
    const b = runQueries([body('b1')]);
    const c = runQueries([body('c1')]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(posts).toHaveLength(1);
    expect(posts[0]).toHaveLength(4);
    expect((await a).map((item) => item.ok && item.result.metric)).toEqual(['a1', 'a2']);
    expect((await b).map((item) => item.ok && item.result.metric)).toEqual(['b1']);
    expect((await c).map((item) => item.ok && item.result.metric)).toEqual(['c1']);
  });

  test('identical items from two widgets are sent once and both are answered', async () => {
    const { runQueries } = createQueryClient(deps);
    const a = runQueries([body('same')]);
    const b = runQueries([body('same')]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(posts[0]).toHaveLength(1);
    expect(await a).toHaveLength(1);
    expect(await b).toHaveLength(1);
  });

  test('more than 32 distinct items split into chunks of at most 32', async () => {
    const { runQueries } = createQueryClient(deps);
    const many = Array.from({ length: 70 }, (_, at) => body(`m${at}`));
    const all = runQueries(many);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(posts.map((chunk) => chunk.length)).toEqual([BATCH_LIMIT, BATCH_LIMIT, 6]);
    const out = await all;
    expect(out).toHaveLength(70);
    expect(out.every((item, at) => item.ok && item.result.metric === `m${at}`)).toBe(true);
  });

  test('a per-item error lands on the widget that asked for it and nowhere else', async () => {
    respond = async (items) => items.map((item) => item.metric === 'bad' ? { ok: false, error: { code: 'query_failed', message: 'over budget' } } : ok(item.metric));
    const { runQueries } = createQueryClient(deps);
    const good = runQueries([body('fine')]);
    const broken = runQueries([body('bad')]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect((await good)[0]).toMatchObject({ ok: true });
    expect((await broken)[0]).toEqual({ ok: false, error: { code: 'query_failed', message: 'over budget' } });
  });

  test('an unmounted widget is dropped: aborted before the window it never reaches the wire, and the other still resolves', async () => {
    const { runQueries } = createQueryClient(deps);
    const gone = new AbortController();
    const leaving = runQueries([body('leaving')], gone.signal);
    const staying = runQueries([body('staying')]);
    gone.abort();
    await expect(leaving).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(posts[0]!.map((item) => item.metric)).toEqual(['staying']);
    expect((await staying)[0]).toMatchObject({ ok: true });
  });

  test('the request is aborted only when every widget that wanted it has left', async () => {
    let seen: AbortSignal | null = null;
    respond = (_items, signal) => { seen = signal; return new Promise(() => {}); };
    const { runQueries } = createQueryClient(deps);
    const one = new AbortController();
    const two = new AbortController();
    const first = runQueries([body('shared')], one.signal);
    const second = runQueries([body('shared')], two.signal);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    one.abort();
    await expect(first).rejects.toMatchObject({ name: 'AbortError' });
    expect(seen!.aborted).toBe(false);
    two.abort();
    await expect(second).rejects.toMatchObject({ name: 'AbortError' });
    expect(seen!.aborted).toBe(true);
  });

  test('a failed request rejects every widget in it', async () => {
    respond = async () => { throw new Error('network down'); };
    const { runQueries } = createQueryClient(deps);
    const a = runQueries([body('a')]);
    const b = runQueries([body('b')]);
    const settled = Promise.allSettled([a, b]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect((await settled).map((item) => item.status)).toEqual(['rejected', 'rejected']);
  });

  test('while the tab is hidden nothing is sent; it leaves once, together, when the tab shows', async () => {
    hidden = true;
    const { runQueries } = createQueryClient(deps);
    const a = runQueries([body('a')]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS * 4);
    expect(posts).toHaveLength(0);
    const b = runQueries([body('b')]);
    await vi.advanceTimersByTimeAsync(COALESCE_MS * 4);
    expect(posts).toHaveLength(0);
    hidden = false;
    visibleCb!();
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(posts).toHaveLength(1);
    expect(posts[0]).toHaveLength(2);
    await Promise.all([a, b]);
  });
});
