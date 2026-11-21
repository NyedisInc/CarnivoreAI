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
import { FOLD_CHARS, askFold, isShiftDismiss, rowFeed } from './task-manager-posts';
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

const THREAD = () => [
  msg(9, 'reply', 'the anchor', { author: 'joe' }),
  msg(10, 'info', 'first info', { unread: true }), msg(11, 'attention', 'a look', { unread: true }),
  msg(12, 'question', 'which one?'), msg(14, 'info', 'late info', { unread: true }),
];

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.calls = [];
  server.items = [mk({ info_unseen: true, info_unread: 2, attention_unseen: true, attention_unread: 1, thread: THREAD() })];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const ids = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-task-manager-feed="1"] > [data-task-manager-post]')].map((n) => n.getAttribute('data-task-manager-post') ?? '');
const seenCalls = () => server.calls.filter((c) => c.path === '/cplugs/huddle/items/1/seen' && c.body);

describe('order', () => {
  test('pure: only Claude posts newer than his latest reply show; his own reply never does', () => {
    expect(rowFeed({ thread: THREAD() } as never).map((m) => m.id)).toEqual([10, 11, 12, 14]);
    const answered = [...THREAD(), msg(13, 'reply', 'the first', { author: 'joe' })];
    expect(rowFeed({ thread: answered } as never).map((m) => m.id)).toEqual([14]);
    expect(rowFeed({ thread: [msg(1, 'reply', 'x', { author: 'joe' })] } as never)).toEqual([]);
  });

  test('the row draws one list of Claude posts, in time order, with none of his', async () => {
    const host = await mountBody();
    expect(ids(host)).toEqual(['10', '11', '12', '14']);
    expect(host.querySelector('[data-by="joe"]')).toBeNull();
  });
});

describe('shift-click', () => {
  test('pure: shift on plain text dismisses; plain click, a link and a button do not', () => {
    const text = document.createElement('span');
    const link = document.createElement('a');
    const button = document.createElement('button');
    expect(isShiftDismiss({ shiftKey: true, target: text })).toBe(true);
    expect(isShiftDismiss({ shiftKey: false, target: text })).toBe(false);
    expect(isShiftDismiss({ shiftKey: true, target: link })).toBe(false);
    expect(isShiftDismiss({ shiftKey: true, target: button })).toBe(false);
  });

  test('shift-click on the text sends the same single read as the icon click', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-post-read="10"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-post="11"] .tkm-post-text')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    await settle();
    expect(seenCalls().map((c) => c.body)).toEqual([{ message: 10 }, { message: 11 }]);
    expect(host.querySelector('[data-task-manager-post="10"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-post="11"]')).toBeNull();
  });

  test('shift-click on the icon reads once, a plain click on the text reads nothing', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-post="14"] .tkm-post-text')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    host.querySelector<HTMLElement>('[data-task-manager-post-read="10"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    await settle();
    expect(seenCalls().map((c) => c.body)).toEqual([{ message: 10 }]);
  });
});

describe('fold', () => {
  const LONG = 'x'.repeat(FOLD_CHARS + 20);

  test('pure: a long plain question folds past the shared threshold; a numbered list shows the lead and the first question', () => {
    expect(askFold({ text: 'short?' }).foldable).toBe(false);
    expect(askFold({ text: LONG }).foldable).toBe(true);
    const numbered = askFold({ text: 'ctx', context: 'why we ask', questions: ['one?', 'two?', 'three?', 'four?'] });
    expect(numbered).toMatchObject({ foldable: true, shown: 1, context: 'why we ask' });
    expect(askFold({ text: 'ctx', context: 'why', questions: ['one?', 'two?'] })).toMatchObject({ foldable: false, shown: 2 });
    const form = { text: 'ctx', context: 'lead line\nthe rest', questions: ['which?'], form: [{ id: 'q1', type: 'single', prompt: 'which?' }] } as never;
    expect(askFold(form).foldable).toBe(false);
    expect(askFold(form, true)).toMatchObject({ foldable: true, context: 'lead line' });
  });

  test('a long question folds behind a chevron and opens inline', async () => {
    server.items = [mk({ thread: [msg(12, 'question', LONG)] })];
    const host = await mountBody();
    const post = host.querySelector<HTMLElement>('[data-task-manager-post="12"]')!;
    expect(post.getAttribute('data-task-manager-post-folded')).toBe('true');
    expect(post.textContent).not.toContain(LONG);
    host.querySelector<HTMLElement>('[data-task-manager-post-fold="12"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-post="12"]')!.textContent).toContain(LONG);
  });

  test('a long numbered list folds to its first question and opens to all', async () => {
    const questions = ['first question here?', 'second question here?', 'third question here?', 'fourth question here?'];
    server.items = [mk({ thread: [msg(12, 'question', 'ctx', { context: 'y'.repeat(FOLD_CHARS), questions })] })];
    const host = await mountBody();
    expect(host.querySelectorAll('[data-task-manager-post="12"] .tkm-ask-q').length).toBe(1);
    host.querySelector<HTMLElement>('[data-task-manager-post-fold="12"]')!.click();
    await settle();
    expect(host.querySelectorAll('[data-task-manager-post="12"] .tkm-ask-q').length).toBe(4);
  });
});
