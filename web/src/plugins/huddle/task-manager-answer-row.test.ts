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

const joeReply = msg(706, 'reply', 'did this just work', { author: 'joe', files: [{ id: 'a1', name: 'shot.png' }] });
const answer = msg(707, 'answer', 'yes, it worked end to end', { unread: true, quote: { id: 706, text: 'did this just work' } });

describe('an answer newer than his reply (item 183)', () => {
  test('pure: it is in the row feed', () => {
    expect(rowFeed(mk({ thread: [joeReply, answer] }) as never).map((m) => m.id)).toEqual([707]);
  });

  test('a review row draws the quote and answer box, with the review block under it', async () => {
    server.items = [mk({ status: 'review', section: 'review', state: 'review', info_unseen: true, info_unread: 1, thread: [joeReply, answer] })];
    const host = await mountBody();
    expect(feedIds(host)).toEqual(['707']);
    expect(host.querySelector('[data-task-manager-post="707"] [data-task-manager-answer-quote]')?.textContent).toContain('did this just work');
  });

  test('the row bubble wears the answer hue, an info beside it the info violet', async () => {
    server.items = [mk({ status: 'review', section: 'review', state: 'review', info_unseen: true, info_unread: 2, thread: [joeReply, msg(708, 'info', 'fyi', { unread: true }), answer] })];
    const host = await mountBody();
    expect((host.querySelector('[data-task-manager-post="707"]') as HTMLElement).style.getPropertyValue('--_post')).toBe('var(--oc-orange)');
    expect((host.querySelector('[data-task-manager-post="708"]') as HTMLElement).style.getPropertyValue('--_post')).toBe('var(--oc-violet)');
  });

  test('an unread info and answer both show on a review row', async () => {
    server.items = [mk({ status: 'review', section: 'review', state: 'review', info_unseen: true, info_unread: 2, thread: [joeReply, msg(708, 'info', 'fyi', { unread: true }), answer] })];
    expect(feedIds(await mountBody())).toEqual(['707', '708']);
  });
});
