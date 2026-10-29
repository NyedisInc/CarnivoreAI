/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const net = vi.hoisted(() => ({ calls: [] as string[], answers: {} as Record<string, unknown> }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const key = `${init.method ?? 'GET'} ${path}`;
      net.calls.push(key);
      return key in net.answers ? structuredClone(net.answers[key]) : {};
    },
  };
});

import { heldRead, huddle, refreshList } from './huddle.svelte';
import { resetHeldReads } from './task-manager-held-read';
import type { HuddleItem, TaskManagerMessage } from './huddle-model';

const msg = (id: number, extra: Partial<TaskManagerMessage> = {}): TaskManagerMessage => ({
  id, item_id: 1, author: 'claude', kind: 'info', text: `m${id}`, answered: false, created_at: id, seq: id, unread: true, ...extra,
});
const unreadItem = (thread: TaskManagerMessage[] = [msg(5)]): HuddleItem => ({
  id: 1, list: '12', text: 'item', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', revision: 3, created_seq: 1, seq: 1,
  deleted: false, status: 'open', section: 'open', needs_you: false, needs_action: null, unread: true, thread, thread_count: thread.length,
} as HuddleItem);
const body = (item: HuddleItem) => ({ list: '12', name: 'p', project_id: 12, revision: 1, items: [item], groups: [] });

async function showUnread(): Promise<HuddleItem> {
  huddle.selected = '12';
  net.answers['GET /cplugs/huddle/lists/12?live_only=1'] = body(unreadItem());
  await refreshList();
  return huddle.body!.items[0]!;
}

/* nothing was written */
async function pushStillUnread(thread?: TaskManagerMessage[]): Promise<HuddleItem> {
  net.answers['GET /cplugs/huddle/lists/12?live_only=1'] = body(unreadItem(thread));
  await refreshList();
  return huddle.body!.items[0]!;
}

beforeEach(() => {
  net.calls.length = 0;
  net.answers = {};
  huddle.openId = null;
  huddle.body = null;
  huddle.groups = null;
  resetHeldReads();
});

describe('a push during the mark read hold', () => {
  test('keeps the task read, and the send is not out yet', async () => {
    const item = await showUnread();
    expect(heldRead(item)).not.toBeNull();
    expect(huddle.body!.items[0]!.unread).toBe(false);
    const after = await pushStillUnread();
    expect(after.unread).toBe(false);
    expect(after.thread.every((m) => !m.unread)).toBe(true);
    expect(net.calls.some((c) => c.startsWith('POST'))).toBe(false);
  });

  test('a message newer than the boundary stays unread', async () => {
    const item = await showUnread();
    heldRead(item);
    const after = await pushStillUnread([msg(5), msg(9)]);
    expect(after.thread.find((m) => m.id === 5)!.unread).toBe(false);
    expect(after.thread.find((m) => m.id === 9)!.unread).toBe(true);
    expect(after.unread).toBe(true);
  });

  test('undo lets the server state show again', async () => {
    const item = await showUnread();
    const held = heldRead(item)!;
    held.undo();
    expect((await pushStillUnread()).unread).toBe(true);
  });

  test('once the write settles the push shows the server truth', async () => {
    const item = await showUnread();
    const held = heldRead(item)!;
    await held.send();
    expect((await pushStillUnread()).unread).toBe(true);
  });
});
