/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const calls: { path: string; body: Record<string, unknown> }[] = [];
let script: (path: string, attempt: number) => unknown = () => ({ ok: true });

vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetch: async (path: string, init: { body?: string } = {}) => {
    calls.push({ path, body: init.body ? JSON.parse(init.body) : {} });
    const out = script(path, calls.filter((c) => c.path === path).length);
    if (out instanceof Error) throw out;
    return out;
  },
}));

import { discard, entries, retryNow, send, startOutbox, stopOutbox } from './outbox';
import { exportText } from './outbox-export';
import { OUTBOX_KEY, resetStore } from './outbox-store';
import type { NewOutboxEntry } from './outbox-model';

function apiError(status: number, code: string | null = null): Error {
  return Object.assign(new Error(`status ${status}`), { status, code, payload: code ? { detail: { code } } : null });
}

function spec(id = 'reply-0001-aaaa', over: Partial<NewOutboxEntry> = {}): NewOutboxEntry {
  return {
    id, kind: 'reply', request: { method: 'POST', path: '/cplugs/huddle/items/7/messages', body: { text: 'ship it, all of this text', client_id: id } },
    ageField: 'retry_age_s', after: { path: '/cplugs/huddle/send', body: { lists: ['18'], queue: true } },
    label: { text: 'ship it, all of this text', where: 'the task', list: '18', item: 7 }, ...over,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  calls.length = 0;
  script = () => ({ ok: true });
  globalThis.localStorage.clear();
  resetStore();
  stopOutbox();
});

afterEach(() => {
  stopOutbox();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('the browser outbox', () => {
  test('storage that throws still sends and keeps the entry in memory', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    script = () => apiError(503);
    const out = await send(spec());
    expect(out).toMatchObject({ ok: false, kept: true });
    expect(entries().map((e) => e.id)).toEqual(['reply-0001-aaaa']);
  });

  test('a network failure keeps it pending; attempt 2 carries the same id and retry_age_s; success removes it and runs the follow-up once', async () => {
    script = (path, attempt) => (path.endsWith('/messages') && attempt === 1 ? apiError(0) : { ok: true });
    const first = await send(spec());
    expect(first).toMatchObject({ ok: false, kept: true });
    expect(entries()[0]).toMatchObject({ state: 'pending', attempts: 1 });
    expect(JSON.parse(globalThis.localStorage.getItem(OUTBOX_KEY) ?? '[]')).toHaveLength(1);
    expect(calls[0]?.body).not.toHaveProperty('retry_age_s');
    await vi.advanceTimersByTimeAsync(2100);
    const sends = calls.filter((c) => c.path.endsWith('/messages'));
    expect(sends).toHaveLength(2);
    expect(sends[1]?.body.client_id).toBe('reply-0001-aaaa');
    expect(sends[1]?.body.retry_age_s).toBeGreaterThanOrEqual(2);
    expect(entries()).toHaveLength(0);
    expect(calls.filter((c) => c.path === '/cplugs/huddle/send')).toHaveLength(1);
  });

  test('a live success removes the entry and does not run the follow-up (the caller tells for itself)', async () => {
    const out = await send(spec());
    expect(out).toMatchObject({ ok: true });
    expect(entries()).toHaveLength(0);
    expect(calls.map((c) => c.path)).toEqual(['/cplugs/huddle/items/7/messages']);
  });

  test('a 422 keeps it failed, hands the cause back, and never retries on its own', async () => {
    script = () => apiError(422, 'task_manager_invalid');
    const out = await send(spec());
    expect(out).toMatchObject({ ok: false, kept: false });
    expect(entries()[0]).toMatchObject({ state: 'failed' });
    await vi.advanceTimersByTimeAsync(600000);
    expect(calls).toHaveLength(1);
    expect(entries()).toHaveLength(1);
    discard('reply-0001-aaaa');
    expect(entries()).toHaveLength(0);
  });

  test('the same id sent twice is one entry', async () => {
    script = () => apiError(500);
    await send(spec());
    await send(spec());
    expect(entries()).toHaveLength(1);
    expect(entries()[0]?.attempts).toBe(2);
  });

  test('a form answer that lost to a different standing answer is kept failed with the server code', async () => {
    script = () => apiError(409, 'task_manager_answered');
    const out = await send(spec('answer-0001-zzzz', { kind: 'answer', ageField: null, after: null }));
    expect(out).toMatchObject({ ok: false, kept: false });
    expect(entries()[0]?.error).toMatchObject({ status: 409, code: 'task_manager_answered' });
  });

  test('a retry key on a refused entry sends it again', async () => {
    script = (path, attempt) => (path.endsWith('/messages') && attempt === 1 ? apiError(400, 'task_manager_invalid') : { ok: true });
    await send(spec());
    const again = await retryNow('reply-0001-aaaa');
    expect(again).toMatchObject({ ok: true });
    expect(entries()).toHaveLength(0);
  });

  test('a retry or a second send of an entry THIS tab is already sending does not post it again (u145-04)', async () => {
    let release: () => void = () => {};
    script = (path) => (path.endsWith('/messages') ? new Promise((resolve) => { release = () => resolve({ ok: true }); }) : { ok: true });
    const first = send(spec());
    await Promise.resolve();
    const replay = await retryNow('reply-0001-aaaa');
    const resend = await send(spec());
    expect(replay).toMatchObject({ ok: false, kept: true });
    expect(resend).toMatchObject({ ok: false, kept: true });
    release();
    await first;
    expect(calls.filter((c) => c.path.endsWith('/messages'))).toHaveLength(1);
    expect(calls.filter((c) => c.path.endsWith('/send'))).toHaveLength(0);
  });

  test('a reload finds the stored copy and sends it', async () => {
    script = () => apiError(0);
    await send(spec());
    stopOutbox();
    resetStore();
    script = () => ({ ok: true });
    startOutbox();
    await vi.advanceTimersByTimeAsync(5000);
    expect(calls.filter((c) => c.path.endsWith('/messages')).length).toBeGreaterThanOrEqual(2);
    expect(entries()).toHaveLength(0);
  });

  test('the export carries the full text', async () => {
    script = () => apiError(0);
    await send(spec());
    expect(exportText(entries())).toContain('ship it, all of this text');
  });

  test('the same id sent again with new words replaces the stale request', async () => {
    script = () => apiError(503);
    await send(spec());
    const edited = spec('reply-0001-aaaa', { request: { method: 'POST', path: '/cplugs/huddle/items/7/messages', body: { text: 'the edited words', client_id: 'reply-0001-aaaa' } } });
    await send(edited);
    expect(calls[calls.length - 1]?.body.text).toBe('the edited words');
    expect(entries()[0]?.request.body.text).toBe('the edited words');
    expect(entries()).toHaveLength(1);
  });

  test('a send stranded by a dead page (sending, lease over, no trigger) is retried at boot', async () => {
    const dead = { ...spec(), created_at: Date.now() - 60000, attempts: 1, next_at: Number.MAX_SAFE_INTEGER, state: 'sending', error: null, lease: { tab: 'gone-tab', until: Date.now() - 1000 } };
    globalThis.localStorage.setItem(OUTBOX_KEY, JSON.stringify([dead]));
    resetStore();
    startOutbox();
    await vi.advanceTimersByTimeAsync(100);
    expect(calls.filter((c) => c.path.endsWith('/messages'))).toHaveLength(1);
    expect(entries()).toHaveLength(0);
  });
});
