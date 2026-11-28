/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';

const wire = vi.hoisted(() => ({ release: (): void => {}, sent: [] as string[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: (path: string, init: RequestInit = {}) => {
      if (init.method === 'POST') wire.sent.push(path);
      return new Promise((resolve) => { wire.release = () => resolve({}); });
    },
  };
});

import { markRead } from './huddle.svelte';
import { applyMarkRead } from './task-manager-optimistic';
import { sectionOf } from './task-manager-status-sections';
import type { HuddleItem } from './huddle-model';

const msg = (id: number, author: string, kind: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author, kind, text: `m${id}`, answered: false, created_at: id, seq: id, ...extra });

const withInfo = (extra: Record<string, unknown> = {}): HuddleItem => ({
  id: 1, list: 'all', text: 'task', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null, revision: 1,
  created_seq: 1, seq: 1, deleted: false, group: 7, status: 'working', section: 'working', unread: true, needs_you: true, needs_action: 'read',
  info_unread: 1, info_unseen: true, thread: [msg(5, 'claude', 'info', { unread: true })], ...extra,
}) as unknown as HuddleItem;

describe('mark read files a task back under its own section', () => {
  test('an unread info leaves "needs you" for its status section, with no refetch', () => {
    const item = withInfo();
    expect(sectionOf(item)).toBe('needs_you');
    applyMarkRead(item);
    expect(sectionOf(item)).toBe('working');
    expect([item.unread, item.needs_you, item.needs_action, item.info_unread, item.info_unseen]).toEqual([false, false, null, 0, false]);
    expect(item.thread[0]?.unread).toBe(false);
  });

  test('an open question stays in "needs you": reading it answers nothing', () => {
    const item = withInfo({ status: 'question', section: 'question', needs_action: 'answer', thread: [msg(6, 'claude', 'question', { unread: true })] });
    applyMarkRead(item);
    expect(sectionOf(item)).toBe('needs_you');
    expect(item.unread).toBe(false);
  });

  test('the undo puts every field back', () => {
    const item = withInfo();
    const undo = applyMarkRead(item);
    undo();
    expect(sectionOf(item)).toBe('needs_you');
    expect([item.unread, item.needs_action, item.info_unread, item.thread[0]?.unread]).toEqual([true, 'read', 1, true]);
  });

  test('a message that arrived after the boundary stays unread', () => {
    const item = withInfo({ thread: [msg(5, 'claude', 'info', { unread: true }), msg(9, 'claude', 'info', { unread: true })] });
    applyMarkRead(item, 5);
    expect(item.thread.map((m) => m.unread)).toEqual([false, true]);
  });
});

describe('markRead', () => {
  test('moves the task before the server answers', async () => {
    const item = withInfo();
    const pending = markRead(item);
    expect(wire.sent.at(-1)).toBe('/cplugs/huddle/items/1/seen');
    expect(sectionOf(item)).toBe('working');
    wire.release();
    await pending;
  });
});
