/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const msg = (id: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });

const mk = (extra: Record<string, unknown> = {}) => ({
  id: 1, list: 'all', text: 'item 1', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: 1, seq: 1, deleted: false, thread: [], unread: false, group: 7, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[], onWrite: (_path: string, _method: string): void => {} }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method && init.method !== 'GET') { server.onWrite(path, init.method); return {}; }
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
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

const THREAD = () => [
  msg(10, 'info', 'early info', { unread: true }), msg(11, 'attention', 'early look', { unread: true }),
  msg(12, 'question', 'which one?'), msg(13, 'info', 'late info', { unread: true }),
];

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.onWrite = () => {};
  server.items = [mk({ status: 'question', section: 'question', info_unseen: true, info_unread: 2, attention_unseen: true, attention_unread: 1, thread: THREAD() })];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(popout: boolean): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

const postIds = (host: HTMLElement): string[] =>
  [...host.querySelectorAll('[data-huddle-item="1"] [data-task-manager-posts] [data-task-manager-post-kind="info"], [data-huddle-item="1"] [data-task-manager-posts] [data-task-manager-post-kind="attention"]')].map((n) => n.getAttribute('data-task-manager-post') ?? '');

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('a reply drops every unread Claude post, the later info included', async () => {
    const host = await mountBody(popout);
    expect(postIds(host)).toEqual(['10', '11', '13']);
    server.onWrite = (path) => {
      if (!path.endsWith('/messages')) return;
      server.items = [mk({ status: 'working', section: 'working', thread: [
        msg(10, 'info', 'early info'), msg(11, 'attention', 'early look'), msg(12, 'question', 'which one?', { answered: true }),
        msg(13, 'info', 'late info'), msg(14, 'reply', 'the first', { author: 'joe' })] })];
    };
    const box = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply="1"]')!;
    box.value = 'the first';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    await refreshTaskManager();
    await settle();
    expect(postIds(host)).toEqual([]);
    expect(host.querySelector('[data-task-manager-feed="1"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-questions="1"]')).toBeNull();
  });

  test('ticking the item off drops every post block', async () => {
    const host = await mountBody(popout);
    expect(postIds(host).length).toBe(3);
    server.onWrite = (path, method) => {
      if (method !== 'PATCH') return;
      server.items = [mk({ state: 'done', status: 'done', section: 'done', thread: [
        msg(10, 'info', 'early info'), msg(11, 'attention', 'early look'), msg(12, 'question', 'which one?'), msg(13, 'info', 'late info')] })];
    };
    host.querySelector<HTMLElement>('[data-task-manager-check="1"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    await refreshTaskManager();
    await settle();
    expect(host.querySelector('[data-task-manager-posts="1"]')).toBeNull();
  });
});
