import { describe, expect, it, vi } from 'vitest';
import type { JobsApi, JobsPage, JobView } from './jobs-api';
import { HISTORY_MAX, JobsStore, type JobsDelta, type JobsDeps } from './jobs-store.svelte';

function job(id: string, extra: Partial<JobView> = {}): JobView {
  return {
    id, side: 'caller', state: 'running', body: 'command', project_uid: 'p1', project_name: 'proj', folder: null, command: `cmd ${id}`, kind: null,
    task_head: null, agent_type: null, computer: 'tower', reason: null, exit_code: null, output_tail: null, applied: [], deleted: [], clashes: [], ref: null,
    error_code: null, error_detail: null, question: null, question_kind: null, result_text: null, account_label: null, usage: null,
    created_at: 1000, started_at: null, ended_at: null, caller_session: 'u1', worker_session_uuid: null, peer_install_id: null, worker_listing_uuid: null, ...extra,
  };
}

function make(answers: Array<JobsPage | (() => Promise<JobsPage>)> = []) {
  const list = vi.fn(async (): Promise<JobsPage> => {
    const next = answers.length > 1 ? answers.shift()! : answers[0];
    return typeof next === 'function' ? next() : (next ?? { jobs: [], next_before: null });
  });
  const api: JobsApi = { list, stop: vi.fn(async () => ({})) };
  let handler: ((frame: JobsDelta) => void) | null = null;
  const deps: JobsDeps = { api, subscribe: (h) => { handler = h; return () => { handler = null; }; }, poll: () => () => {}, repaint: vi.fn() };
  const store = new JobsStore(deps);
  return { store, list, api, deps, frame: (f: JobsDelta) => handler?.(f) };
}

describe('frames', () => {
  it('add, update and remove a row', () => {
    const { store } = make();
    store.apply({ seq: 1, job: job('a') });
    expect(store.live.map((j) => j.id)).toEqual(['a']);
    store.apply({ seq: 2, job: job('a', { state: 'question', question: 'ok?' }) });
    expect(store.live[0]!.state).toBe('question');
    store.apply({ seq: 3, job: job('a', { state: 'done', ended_at: 1010 }) });
    expect(store.live).toEqual([]);
    expect(store.history.map((j) => j.id)).toEqual(['a']);
    store.apply({ seq: 4, removed: ['a'] });
    expect(store.history).toEqual([]);
  });

  it('a warm-up row is not a job: it is left out of every list and count', () => {
    const { store } = make();
    store.apply({ seq: 1, job: job('warm-123', { side: 'host', state: 'running', caller_session: null }) });
    expect(Object.keys(store.rows)).toEqual([]);
    expect(store.live).toEqual([]);
  });

  it('a host row is live while running and never counts for a session', () => {
    const { store } = make();
    store.apply({ seq: 1, job: job('h1', { side: 'host', state: 'running', caller_session: null }) });
    store.apply({ seq: 2, job: job('c1') });
    expect(store.live.map((j) => j.id).sort()).toEqual(['c1', 'h1']);
    expect(store.liveFor('u1').map((j) => j.id)).toEqual(['c1']);
    store.apply({ seq: 3, job: job('h1', { side: 'host', state: 'exited', caller_session: null }) });
    expect(store.live.map((j) => j.id)).toEqual(['c1']);
  });
});

describe('a sequence gap', () => {
  it('refetches the live list once, and a second gap while it is in flight waits for it', async () => {
    let release: (page: JobsPage) => void = () => {};
    const slow = (): Promise<JobsPage> => new Promise((resolve) => { release = resolve; });
    const { store, list } = make([slow]);
    store.apply({ seq: 1, job: job('a') });
    store.apply({ seq: 2, job: job('a') });
    expect(list).not.toHaveBeenCalled();
    store.apply({ seq: 5, job: job('b') });
    store.apply({ seq: 9, job: job('c') });
    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith({ live: true, limit: 200 });
    release({ jobs: [job('a', { state: 'running' }), job('b', { state: 'running' }), job('gone-from-server')], next_before: null });
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(list).toHaveBeenCalledTimes(1);
    expect(Object.keys(store.rows).sort()).toEqual(['a', 'b', 'c', 'gone-from-server']);
  });

  it('a live row the server no longer lists is dropped, and a frame that landed during the read wins over its answer', async () => {
    let release: (page: JobsPage) => void = () => {};
    const { store, list } = make([() => new Promise((resolve) => { release = resolve; })]);
    store.apply({ seq: 1, job: job('stale') });
    store.apply({ seq: 7, job: job('x') });
    expect(list).toHaveBeenCalledTimes(1);
    store.apply({ seq: 8, job: job('x', { state: 'done', ended_at: 5 }) });
    release({ jobs: [job('x', { state: 'running' })], next_before: null });
    await vi.waitFor(() => expect(store.loading).toBe(false));
    expect(store.rows.x!.state).toBe('done');
    expect(store.rows.stale).toBeUndefined();
  });
});

describe('history', () => {
  it('holds at most 200 rows and keeps the newest', () => {
    const { store } = make();
    for (let i = 0; i < HISTORY_MAX + 50; i += 1) store.apply({ job: job(`d${i}`, { state: 'done', created_at: 1000 + i, ended_at: 2000 }) });
    expect(store.history).toHaveLength(HISTORY_MAX);
    expect(store.rows[`d${HISTORY_MAX + 49}`]).toBeDefined();
    expect(store.rows.d0).toBeUndefined();
  });

  it('loads only while the tab is shown and the filter is all, one page at a time', async () => {
    const page = (n: number, next: string | null): JobsPage => ({ jobs: [job(`h${n}`, { state: 'done', created_at: 500 - n, ended_at: 600 })], next_before: next });
    const { store, list } = make([{ jobs: [], next_before: null }, page(1, 'c|h1'), page(2, null)]);
    store.setFilter('all');
    await store.loadMore();
    expect(list).not.toHaveBeenCalled();
    store.setVisible(true);
    await vi.waitFor(() => expect(store.historyLoaded).toBe(true));
    const calls = list.mock.calls as unknown as Array<[{ live?: boolean; before?: string | null }]>;
    expect(calls.some(([q]) => q.live === true)).toBe(true);
    await store.loadMore();
    await vi.waitFor(() => expect(store.canMore).toBe(false));
    expect(calls.some(([q]) => q.before === 'c|h1')).toBe(true);
    expect(store.history.map((j) => j.id).sort()).toEqual(['h1', 'h2']);
  });
});

describe('the caller chip', () => {
  it('shows one session’s caller rows only, and drops host rows', () => {
    const { store } = make();
    store.apply({ seq: 1, job: job('a', { caller_session: 'u1' }) });
    store.apply({ seq: 2, job: job('b', { caller_session: 'u2' }) });
    store.apply({ seq: 3, job: job('h', { side: 'host', caller_session: null }) });
    expect(store.live).toHaveLength(3);
    store.setCaller('u1');
    expect(store.live.map((j) => j.id)).toEqual(['a']);
    store.setCaller(null);
    expect(store.live).toHaveLength(3);
  });
});

describe('stop', () => {
  it('sends one post and leaves the row alone until the frame arrives', async () => {
    const { store, api } = make();
    store.apply({ seq: 1, job: job('a') });
    await store.stopJob('a');
    expect(api.stop).toHaveBeenCalledTimes(1);
    expect(store.rows.a!.state).toBe('running');
  });
});
