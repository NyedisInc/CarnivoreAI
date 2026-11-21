/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as { path: string; method: string; body: unknown }[] }));

const mk = (id: number) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, status: 'working',
  thread: [
    { id: 20 + id, item_id: id, author: 'claude', kind: 'attention', text: 'first', answered: false, created_at: 0, seq: 1, unread: true },
    { id: 30 + id, item_id: id, author: 'claude', kind: 'info', text: 'newest', answered: false, created_at: 0, seq: 2, unread: true },
    { id: -5, item_id: id, author: 'joe', kind: 'reply', text: 'optimistic', answered: false, created_at: 0, seq: 2 },
  ],
  unread: true, info_unseen: true, attention_unseen: true, info_unread: 1, attention_unread: 1,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 1, waiting_to_send: 0 }] };
      }
      if (path.endsWith('/sessions')) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: [mk(1)] };
      if (/\/seen$/.test(path)) return mk(1);
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { boundaryOf } from './task-manager-boundary';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  server.calls.length = 0;
});

const seenCalls = (): { body: unknown }[] => server.calls.filter((c) => c.path.endsWith('/seen'));

describe('the unread boundary', () => {
  test('boundaryOf is the newest incoming message id, ignoring his own and optimistic ones', () => {
    expect(boundaryOf(mk(1))).toBe(31);
    expect(boundaryOf({ thread: [] })).toBeUndefined();
    expect(boundaryOf(null)).toBeUndefined();
  });

  test('opening a row and pressing inside it send no read; Mark read sends the boundary', async () => {
    huddle.selected = 'all';
    huddle.openId = null;
    await refreshTaskManager();
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-huddle-item="1"]')!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    host.querySelector<HTMLElement>('[data-huddle-item="1"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    await settle();
    expect(huddle.openId).toBe(1);
    expect(seenCalls()).toEqual([]);
    const button = host.querySelector<HTMLElement>('[data-task-manager-mark-read="1"]');
    expect(button).not.toBeNull();
    button!.click();
    await settle();
    expect(seenCalls().map((c) => c.body)).toEqual([{ through: 31 }]);
  });
});
