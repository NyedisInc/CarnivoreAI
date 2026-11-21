/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const net = vi.hoisted(() => ({
  calls: [] as string[],
  held: new Map<string, () => void>(),
  refuse: new Set<string>(),
  answers: {} as Record<string, unknown>,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const key = `${init.method ?? 'GET'} ${path}`;
      net.calls.push(key);
      const hold = net.held.get(`hold ${key}`);
      if (hold !== undefined) await new Promise<void>((release) => net.held.set(key, release));
      if (net.refuse.has(key)) throw new real.ApiError('refused', 409, 'task_manager_stale', { detail: { code: 'task_manager_stale' } });
      return key in net.answers ? structuredClone(net.answers[key]) : {};
    },
  };
});

import { huddle, loadThread, reply, setApproved, write } from './huddle.svelte';
import { applyAnswered, applyReply, applyTick, mergeThread, threadCount } from './task-manager-optimistic';
import { applyFlushHold, holdFlushed, resetFlushHold, HOLD_MS } from './task-manager-flush-hold';
import { applyQueue, resetSendQueue, sendQueue, type SendQueueState } from './task-manager-send-queue.svelte';
import { waitingToSend } from './huddle-send-many.svelte';
import { createAsk } from './ask/ask-state.svelte';
import { AGGREGATE, type HuddleItem, type TaskManagerListRow, type TaskManagerMessage } from './huddle-model';

const msg = (id: number, extra: Partial<TaskManagerMessage> = {}): TaskManagerMessage => ({
  id, item_id: 1, author: 'claude', kind: 'info', text: `m${id}`, answered: false, created_at: id, seq: id, ...extra,
});
const mk = (extra: Partial<HuddleItem> = {}): HuddleItem => ({
  id: 1, list: '12', text: 'item', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', revision: 3, created_seq: 1, seq: 1,
  deleted: false, status: 'question', section: 'question', needs_you: true, needs_action: 'answer',
  thread: [msg(5, { kind: 'question' })], ...extra,
});
const row = (key: string, waiting: number): TaskManagerListRow => ({
  key, name: key, project_id: Number(key), items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, waiting_to_send: waiting, untold: waiting > 0,
});

function shown(): HuddleItem {
  return huddle.groups![0]!.items[0]!;
}

function showItem(item: HuddleItem): HuddleItem {
  huddle.selected = AGGREGATE;
  huddle.groups = [{ list: item.list, name: 'p', project_id: 12, revision: 1, items: [item] }];
  return shown();
}

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
}

beforeEach(() => {
  net.calls.length = 0;
  net.held.clear();
  net.refuse.clear();
  net.answers = {};
  huddle.notice = '';
  huddle.openId = null;
  huddle.lists = [];
  resetFlushHold();
  resetSendQueue();
});
afterEach(() => vi.restoreAllMocks());

describe('optimistic steps (pure)', () => {
  test('a tick files the item under waiting to send, out of needs you, and the undo puts it all back', () => {
    const item = mk();
    const undo = applyTick(item, true);
    expect([item.state, item.status, item.section, item.needs_you, item.needs_action]).toEqual(['done', 'waiting_to_send', 'waiting_to_send', false, null]);
    undo();
    expect([item.state, item.status, item.needs_you, item.needs_action]).toEqual(['open', 'question', true, 'answer']);
  });

  test('an untick draws review, never open: the reopen goes back to where the task was and the owner can see it (#2679)', () => {
    const item = mk({ state: 'done', status: 'done' });
    applyTick(item, false);
    expect(item.state).toBe('review');
  });

  test('a tick on an item with a note is approved with the note; a parked item stays parked', () => {
    const noted = mk({ note: 'read me' });
    applyTick(noted, true);
    expect(noted.state).toBe('done');
    const parked = mk({ status: 'todo', section: 'todo', needs_you: false });
    applyTick(parked, true);
    expect(parked.status).toBe('todo');
  });

  test('an answer closes the one question; the item leaves needs you only when none is left', () => {
    const item = mk({ thread: [msg(5, { kind: 'question' }), msg(6, { kind: 'question' })] });
    const undo = applyAnswered(item, 5);
    expect(item.needs_you).toBe(true);
    applyAnswered(item, 6);
    expect(item.thread.every((m) => m.answered)).toBe(true);
    expect([item.needs_you, item.status]).toEqual([false, 'waiting_to_send']);
    undo();
    expect(item.thread.find((m) => m.id === 5)?.answered).toBe(false);
  });

  test('a reply joins the thread and counts; the undo takes it out', () => {
    const item = mk({ thread_count: 9, thread_slim: true });
    const undo = applyReply(item, 'ship it', 100);
    expect(item.thread.at(-1)).toMatchObject({ author: 'joe', kind: 'reply', text: 'ship it' });
    expect(item.thread.at(-1)!.id).toBeLessThan(0);
    expect(threadCount(item)).toBe(10);
    undo();
    expect([item.thread.length, threadCount(item)]).toEqual([1, 9]);
  });

  test('a reply on a review or done item draws it open at once (R92), and the undo puts the state back', () => {
    for (const state of ['review', 'done']) {
      const item = mk({ state, status: state });
      const undo = applyReply(item, 'why?', 100);
      expect([item.state, item.status]).toEqual(['open', 'waiting_to_send']);
      undo();
      expect(item.state).toBe(state);
    }
  });

  test('mergeThread completes a slim item from the loaded thread, fresh messages win, provisional ones go', () => {
    const fresh = mk({ thread_slim: true, thread_count: 4, thread: [msg(3, { text: 'newer' }), msg(4)] });
    const merged = mergeThread(fresh, [msg(1), msg(2), msg(3, { text: 'old' }), msg(-9)]);
    expect(merged.thread.map((m) => [m.id, m.text])).toEqual([[1, 'm1'], [2, 'm2'], [3, 'newer'], [4, 'm4']]);
    expect(mergeThread(mk(), [msg(1)]).thread.map((m) => m.id)).toEqual([5]);
  });
});

describe('writes', () => {
  test('a tick is drawn before the request leaves and the call resolves without waiting for a re-read', async () => {
    const item = showItem(mk());
    net.held.set('hold PATCH /cplugs/huddle/items/1', () => {});
    const done = setApproved(item, true);
    await settle();
    expect(shown()).toMatchObject({ state: 'done', needs_you: false });
    net.held.get('PATCH /cplugs/huddle/items/1')!();
    expect(await done).toBe(true);
    net.held.set('hold GET /cplugs/huddle/aggregate?live_only=1', () => {});
    net.held.set('hold GET /cplugs/huddle/lists', () => {});
    expect(await write(async () => undefined, () => {})).toBe(true);
  });

  test('a write with its own optimistic step starts no re-read while the push is live', async () => {
    const { resourcePush } = await import('../sdk');
    resourcePush().store.hello({ resource_topics: ['cplug.huddle.list'] });
    const item = showItem(mk());
    await setApproved(item, true);
    await settle();
    expect(net.calls.filter((c) => c.startsWith('GET'))).toEqual([]);
    resourcePush().store.closed();
  });

  test('a refused tick rolls back, says why and re-reads', async () => {
    const item = showItem(mk());
    net.refuse.add('PATCH /cplugs/huddle/items/1');
    expect(await setApproved(item, true)).toBe(false);
    expect(shown()).toMatchObject({ state: 'open', needs_you: true, status: 'question' });
    expect(huddle.notice).not.toBe('');
    await settle();
    expect(net.calls).toContain('GET /cplugs/huddle/lists');
  });

  test('a refused reply takes the provisional message back out', async () => {
    const item = showItem(mk());
    net.refuse.add('POST /cplugs/huddle/items/1/messages');
    expect(await reply(item, 'hello')).toBe(false);
    expect(shown().thread.map((m) => m.id)).toEqual([5]);
  });
});

describe('the answer form', () => {
  const form = { item: 1, message: 5, typed: true, answered: false, answer_message_id: null, ask: { context: '', questions: [{ id: 'q', type: 'yes_no', prompt: 'ok?', required: true }] } };

  test('submit resolves true before the answer reaches the server, the row already left needs you', async () => {
    const item = showItem(mk());
    net.answers['GET /cplugs/huddle/questions/5'] = form;
    net.held.set('hold POST /cplugs/huddle/questions/5/answer', () => {});
    const ask = createAsk(5);
    await ask.load();
    ask.set('q', { value: true });
    const closed = await ask.submit();
    expect(closed).toBe(true);
    await settle();
    expect(net.held.has('POST /cplugs/huddle/questions/5/answer')).toBe(true);
    expect(shown()).toMatchObject({ needs_you: false, status: 'waiting_to_send' });
    expect(net.calls).not.toContain('POST /cplugs/huddle/send');
    net.held.get('POST /cplugs/huddle/questions/5/answer')!();
    await settle();
    expect(net.calls).toContain('POST /cplugs/huddle/send');
    expect(item.id).toBe(1);
  });

  test('a refused answer is taken back and the notice says why', async () => {
    showItem(mk());
    net.answers['GET /cplugs/huddle/questions/5'] = form;
    net.answers['GET /cplugs/huddle/aggregate?live_only=1'] = { cursor: 1, groups: [{ list: '12', name: 'p', project_id: 12, revision: 1, items: [mk()] }] };
    net.refuse.add('POST /cplugs/huddle/questions/5/answer');
    const ask = createAsk(5);
    await ask.load();
    ask.set('q', { value: true });
    expect(await ask.submit()).toBe(true);
    await settle();
    expect(shown()).toMatchObject({ needs_you: true, status: 'question' });
    expect(huddle.notice).not.toBe('');
    expect(ask.answered).toBe(false);
  });
});

describe('the tell badge', () => {
  const queue = (lists: Record<string, number>): SendQueueState => ({
    now: 1000, quiet_s: 8, cap_s: 30, count: Object.values(lists).reduce((a, b) => a + b, 0), first_at: 990, reset_at: 995, due_at: 1003,
    lists: Object.fromEntries(Object.entries(lists).map(([k, count]) => [k, { count, first_at: 990, last_at: 995, due_at: 1003 }])),
  });

  test('the read that no longer names a list clears its waiting count at once', () => {
    huddle.lists = [row('12', 2), row('18', 1)];
    applyQueue(queue({ '12': 2 }));
    expect(waitingToSend(AGGREGATE, huddle.lists)).toBe(1 + 2);
    applyQueue(queue({}));
    expect(huddle.lists.map((r) => [r.key, r.waiting_to_send, r.untold])).toEqual([['12', 0, false], ['18', 1, true]]);
    expect(sendQueue.state?.count).toBe(0);
  });

  test('a lists read that left before the tell was recorded cannot paint the old count back; the server catching up releases the hold', () => {
    holdFlushed(['12'], 1_000);
    expect(applyFlushHold([row('12', 2)], 2_000)[0]!.waiting_to_send).toBe(0);
    expect(applyFlushHold([row('12', 0)], 3_000)[0]!.waiting_to_send).toBe(0);
    expect(applyFlushHold([row('12', 2)], 4_000)[0]!.waiting_to_send).toBe(2);
  });

  test('a hold ends after its time, so a tell that never placed shows its count again', () => {
    holdFlushed(['12'], 0);
    expect(applyFlushHold([row('12', 2)], HOLD_MS + 1)[0]!.waiting_to_send).toBe(2);
  });
});

describe('slim threads', () => {
  test('loadThread draws the whole thread into the open row and marks it whole', async () => {
    const slim = mk({ thread_slim: true, thread_count: 3, thread: [msg(3)] });
    showItem(slim);
    net.answers['GET /cplugs/huddle/items/1'] = { ...mk(), thread: [msg(1), msg(2), msg(3)] };
    await loadThread(1);
    expect(shown()).toMatchObject({ thread_slim: false, thread_count: 3 });
    expect(shown().thread.map((m) => m.id)).toEqual([1, 2, 3]);
  });

  test('an item that is gone leaves the slim thread alone', async () => {
    showItem(mk({ thread_slim: true, thread_count: 3, thread: [msg(3)] }));
    net.refuse.add('GET /cplugs/huddle/items/1');
    await loadThread(1);
    expect(shown().thread.map((m) => m.id)).toEqual([3]);
  });
});

describe('a thread load the read order refused (issue #2671)', () => {
  test('is read again once the write that refused it settles', async () => {
    showItem(mk({ thread_slim: true, thread_count: 3, thread: [msg(3)] }));
    net.answers['GET /cplugs/huddle/items/1'] = { ...mk(), thread: [msg(1), msg(2), msg(3)] };
    const pending = write(async () => { await new Promise<void>((r) => setTimeout(r, 20)); }, () => {});
    await loadThread(1);
    expect(shown().thread_slim).toBe(true);
    await pending;
    await new Promise<void>((r) => setTimeout(r, 30));
    expect(net.calls.filter((c) => c === 'GET /cplugs/huddle/items/1').length).toBe(2);
  });
});
