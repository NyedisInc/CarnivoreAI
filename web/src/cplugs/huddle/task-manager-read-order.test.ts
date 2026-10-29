import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

interface Call { path: string; method: string; resolve: (value: unknown) => void }

const server = vi.hoisted(() => ({ held: [] as Call[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method === 'GET' && path === '/cplugs/huddle/lists') return Promise.resolve({ cursor: 0, lists: [] });
      if (method === 'GET' && path === '/cplugs/huddle/held') return Promise.resolve({ held: [] });
      return new Promise((resolve) => server.held.push({ path, method, resolve }));
    },
  };
});

import { huddle, readPost, refreshList, reply } from './huddle.svelte';
import { hasOpenQuestion, type HuddleItem, type TaskManagerListBody, type TaskManagerMessage } from './huddle-model';

const post = (unread: boolean) => ({ id: 5, item_id: 1, author: 'claude', kind: 'info', text: 'fyi', answered: false, created_at: 5, seq: 5, unread });
const item = (extra: Record<string, unknown>): HuddleItem => ({
  id: 1, list: 'all', text: 'item 1', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: 1, seq: 1, deleted: false, thread: [], unread: false, ...extra,
}) as unknown as HuddleItem;
const body = (one: HuddleItem): TaskManagerListBody => ({ list: 'all', revision: 1, cursor: 1, groups: [], items: [one] });

const unreadInfo = () => item({ info_unseen: true, info_unread: 1, thread: [post(true)] });
const readInfo = () => item({ info_unseen: false, info_unread: 0, thread: [post(false)] });
const asking = () => item({ kind: 'question', status: 'question', section: 'question' });
const answered = () => item({ kind: 'question', status: 'open', section: 'open', thread: [{ ...post(false), kind: 'reply', author: 'joe' }] });

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

async function answer(path: string, method: string, value: unknown): Promise<void> {
  const at = server.held.findIndex((c) => c.path === path && c.method === method);
  if (at < 0) throw new Error(`no held ${method} ${path}`);
  server.held.splice(at, 1)[0]?.resolve(value);
  await flush();
}

const LIST = '/cplugs/huddle/lists/all?live_only=1';
const shown = (): HuddleItem => huddle.body?.items[0] as HuddleItem;
const firstPost = (): TaskManagerMessage => shown().thread[0] as TaskManagerMessage;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  server.held = [];
  huddle.selected = 'all';
  huddle.body = null;
  huddle.groups = null;
});

afterEach(async () => {
  vi.runOnlyPendingTimers();
  await flush();
  vi.useRealTimers();
});

describe('a stale read never resurrects what the owner just cleared', () => {
  test('marking a post read: the post stays gone through a read that left before the write', async () => {
    const first = refreshList();
    await answer(LIST, 'GET', body(unreadInfo()));
    await first;
    const trace: boolean[] = [firstPost().unread === true];

    const stale = refreshList();
    await flush();
    const marking = readPost(shown(), firstPost());
    trace.push(firstPost().unread === true);
    await answer('/cplugs/huddle/items/1/seen', 'POST', {});
    await marking;
    trace.push(firstPost().unread === true);
    await answer(LIST, 'GET', body(unreadInfo()));
    await stale;
    trace.push(firstPost().unread === true);
    vi.runOnlyPendingTimers();
    const fresh = refreshList();
    await flush();
    while (server.held.some((c) => c.path === LIST)) await answer(LIST, 'GET', body(readInfo()));
    await fresh;
    trace.push(firstPost().unread === true);

    expect(trace).toEqual([true, false, false, false, false]);
  });

  test('answering a question: the row never moves back to the question once the fresh read has painted it', async () => {
    const first = refreshList();
    await answer(LIST, 'GET', body(asking()));
    await first;
    const trace: boolean[] = [hasOpenQuestion(shown())];

    const stale = refreshList();
    await flush();
    const sending = reply(shown(), '1');
    await answer('/cplugs/huddle/items/1/messages', 'POST', {});
    const reads = server.held.filter((c) => c.path === LIST);
    expect(reads.length).toBe(2);
    const own = reads[1] as Call;
    server.held.splice(server.held.indexOf(own), 1);
    own.resolve(body(answered()));
    await flush();
    await sending;
    trace.push(hasOpenQuestion(shown()));
    await answer(LIST, 'GET', body(asking()));
    await stale;
    trace.push(hasOpenQuestion(shown()));
    vi.runOnlyPendingTimers();
    await flush();
    while (server.held.some((c) => c.path === LIST)) await answer(LIST, 'GET', body(answered()));
    trace.push(hasOpenQuestion(shown()));

    expect(trace).toEqual([true, false, false, false]);
  });
});
