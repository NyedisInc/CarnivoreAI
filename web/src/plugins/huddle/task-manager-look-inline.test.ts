/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, section: string, position: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: 7, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({ view: 'status', items: [] as unknown[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 6, open: 6, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'huddle', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { SECTION_ICON, SECTION_ORDER } from './task-manager-status-sections';
import { statusFolds } from './task-manager-status-folds.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

const LIST = () => [
  mk(1, 'open', 0), mk(2, 'working', 1), mk(3, 'working', 2, { info_unseen: true, info_unread: 1, thread: [{ id: 30, item_id: 3, author: 'claude', kind: 'info', text: 'fyi', answered: false, created_at: 1, seq: 3, unread: true }] }),
  mk(4, 'open', 3, { attention_unseen: true, attention_unread: 1, unread: true, thread: [{ id: 40, item_id: 4, author: 'claude', kind: 'attention', text: 'a look', answered: false, created_at: 1, seq: 4, unread: true }] }), mk(5, 'review', 4, { state: 'review' }), mk(6, 'question', 5),
];

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = LIST();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(view: string, popout: boolean): Promise<HTMLElement> {
  server.view = view;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

test('the order is question, review, waiting to install, working, scheduled, open, back burner, done; no info or look section', () => {
  expect([...SECTION_ORDER]).toEqual(['needs_you', 'question', 'review', 'waiting', 'working', 'scheduled', 'open', 'todo', 'done']);
  expect(Object.keys(SECTION_ICON)).not.toContain('look');
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('a look never moves the item: it stays in open, wears its status icon, and shows the look in full with the look icon', async () => {
    const host = await mountBody('status', popout);
    const heads = [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-head]')].map((h) => h.dataset.taskManagerStatusHead);
    expect(heads).toEqual(['question', 'review', 'working', 'open']);
    expect(host.querySelector('[data-task-manager-status-head="look"]')).toBeNull();
    expect(host.querySelector<HTMLElement>('[data-huddle-item="4"]')!.dataset.status).toBe('open');
    expect(host.querySelector('[data-huddle-item="4"] [data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('open');
    expect(host.querySelector('[data-huddle-mark-read]')).toBeNull();
    const look = host.querySelector<HTMLElement>('[data-huddle-item="4"] [data-task-manager-post-kind="attention"]')!;
    expect(look.textContent).toContain('a look');
    expect(look.querySelector('[data-task-manager-post-read="40"] svg')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="3"] [data-task-manager-post-kind="info"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="3"] [data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('working');
  });

  test('by area, the subsections carry no look subsection', async () => {
    const host = await mountBody('area', popout);
    const subs = [...host.querySelectorAll('.hds-sub .hds-sub-name')].map((n) => n.textContent);
    expect(subs.slice(0, 3)).toEqual(['huddle: question for you', 'huddle: ready to review', 'huddle: working']);
    expect(subs.some((n) => /look/.test(n ?? ''))).toBe(false);
  });
});
