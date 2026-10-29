/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const msg = (id: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });
const mk = (extra: Record<string, unknown> = {}) => ({
  id: 1, list: 'all', text: 'item 1', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: 1, seq: 1, deleted: false, thread: [], unread: false, group: 7, status: 'question', section: 'question', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[], calls: [] as { path: string; body: unknown }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 1, claude_seq: 0, unread: 0 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'huddle', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { refreshTaskManager, huddle } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { statusFolds } from './task-manager-status-folds.svelte';
import { rowFeed } from './task-manager-posts';
import { hasOpenQuestion } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function mountBody(): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}


beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.calls = [];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const feedIds = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-task-manager-feed="1"] > [data-task-manager-post]')].map((n) => n.getAttribute('data-task-manager-post') ?? '');

describe('an item-level question', () => {
  test('pure: pending until a reply, a question post, or the server leaves status question', () => {
    const own = mk({ kind: 'question', text: 'review area rework?' }) as never;
    expect(hasOpenQuestion(own)).toBe(true);
    expect(rowFeed(own).map((m) => [m.kind, m.text])).toEqual([['question', 'review area rework?']]);
    expect(hasOpenQuestion(mk({ kind: 'question', status: 'open' }) as never)).toBe(false);
    expect(hasOpenQuestion(mk({ kind: 'question', status: undefined, thread: [msg(3, 'reply', 'ok', { author: 'joe' })] }) as never)).toBe(false);
    expect(rowFeed(mk({ kind: 'question', thread: [msg(3, 'question', 'real one')] }) as never).map((m) => m.id)).toEqual([3]);
    expect(hasOpenQuestion(mk({ kind: 'info' }) as never)).toBe(false);
  });

  test('the row draws the question bubble with the pending marker and the reply box', async () => {
    server.items = [mk({ kind: 'question', text: 'review area rework?' })];
    const host = await mountBody();
    const bubble = host.querySelector('[data-task-manager-feed="1"] [data-task-manager-post-kind="question"]');
    expect(bubble?.textContent).toContain('review area rework?');
    expect(host.querySelector('.tkm-asking')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-question-reply="1"]')).not.toBeNull();
  });
});

describe('their reply clears the row', () => {
  test('pure: only Claude posts newer than their latest reply', () => {
    const thread = [msg(1, 'info', 'old', { unread: true }), msg(2, 'reply', 'mine', { author: 'joe' }), msg(3, 'info', 'new', { unread: true })];
    expect(rowFeed({ thread } as never).map((m) => m.id)).toEqual([3]);
    expect(rowFeed({ thread: thread.slice(0, 2) } as never)).toEqual([]);
  });

  test('the row shows only the newer Claude post; their reply and the older unread post are gone from the row', async () => {
    server.items = [mk({ info_unseen: true, info_unread: 2, thread: [msg(1, 'info', 'old', { unread: true }), msg(2, 'reply', 'mine', { author: 'joe' }), msg(3, 'info', 'new', { unread: true })] })];
    const host = await mountBody();
    expect(feedIds(host)).toEqual(['3']);
  });
});
