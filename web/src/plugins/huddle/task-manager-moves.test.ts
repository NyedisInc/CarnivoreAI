/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ calls: [] as { method: string; path: string }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ method: init.method ?? 'GET', path });
      return {};
    },
  };
});
vi.mock('./huddle-send-many.svelte', () => ({ sendLists: async () => true }));

import { askDelete, closeTickConfirm, tickConfirm } from './task-manager-tick-confirm.svelte';
import { AGGREGATE, needsYouTotal } from './huddle-model';
import TaskManagerTickConfirm from './TaskManagerTickConfirm.svelte';
import HuddleReply from './HuddleReply.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; closeTickConfirm(); server.calls.length = 0; document.body.innerHTML = ''; });

describe('delete for good', () => {
  test('the remove key asks first; cancel sends nothing, delete sends the DELETE', async () => {
    app = mount(TaskManagerTickConfirm, { target: document.body });
    await tick();
    askDelete(mk(7) as never);
    flushSync();
    expect(document.querySelector('[data-task-manager-confirm-mode="delete"]')).not.toBeNull();
    expect(document.body.textContent).toContain('delete for good?');
    expect(server.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0);
    document.querySelector<HTMLElement>('[data-task-manager-tick-cancel]')!.click();
    flushSync();
    expect(tickConfirm.open).toBe(false);
    expect(server.calls.filter((c) => c.method === 'DELETE')).toHaveLength(0);
    askDelete(mk(8) as never);
    flushSync();
    document.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')!.click();
    await tick(); await tick();
    expect(server.calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/cplugs/huddle/items/8']);
  });
});

describe('cancel a question', () => {
  test('a question item has no cancel key: the reply answers it', async () => {
    app = mount(HuddleReply, { target: document.body, props: { item: mk(9, { status: 'question' }) as never } });
    await tick();
    expect(document.querySelector('[data-huddle-cancel-question]')).toBeNull();
    expect(document.querySelector('[data-huddle-reply="9"]')).not.toBeNull();
  });
});

describe('attention badge', () => {
  test('counts questions plus reviews, falling back to needs_you from an older server', () => {
    const lists = [{ key: '18', attention: 3, needs_you: 1 }, { key: '19', needs_you: 2 }];
    expect(needsYouTotal(lists, '18')).toBe(3);
    expect(needsYouTotal(lists, '19')).toBe(2);
    expect(needsYouTotal(lists, AGGREGATE)).toBe(5);
  });
});
