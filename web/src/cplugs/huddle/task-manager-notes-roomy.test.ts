/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const msg = (id: number, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 1, author: 'claude', kind, text, answered: false, created_at: id, seq: id, ...extra });

const mk = (extra: Record<string, unknown> = {}) => ({
  id: 1, list: 'all', text: 'item 1', note: '', position: 1, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: 1, seq: 1, deleted: false, thread: [], unread: false, group: 7, status: 'working', section: 'working', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[], calls: [] as { path: string; method: string; body: unknown }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : null });
      if (init.method && init.method !== 'GET') return {};
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
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
import { FOLD_CHARS, postFold } from './task-manager-posts';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

const LONG = `${'word '.repeat(80)}end`;
const LEAD = 'short lead line\nthen the details of the message that go on and on. '.concat('detail '.repeat(40));

beforeEach(() => {
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  server.calls = [];
  server.items = [mk({ info_unseen: true, info_unread: 3, thread: [
    msg(10, 'info', 'a short info', { unread: true }), msg(11, 'info', LONG, { unread: true }), msg(12, 'info', LEAD, { unread: true })] })];
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

const post = (host: HTMLElement, id: number): HTMLElement => host.querySelector<HTMLElement>(`[data-task-manager-post="${id}"]`)!;

describe('postFold (pure)', () => {
  test('a short post does not fold', () => {
    expect(postFold('short')).toMatchObject({ foldable: false, folded: 'short' });
  });
  test('a long post folds to whole lines, cut to FOLD_CHARS by the renderer with an ellipsis', () => {
    const f = postFold(LONG);
    expect(f.foldable).toBe(true);
    expect(f.lead).toBe(false);
    expect(f).toMatchObject({ limit: FOLD_CHARS, more: true });
    expect(LONG.startsWith(f.folded)).toBe(true);
  });
  test('a short first line is the lead, and more than three lines folds', () => {
    expect(postFold(LEAD)).toMatchObject({ foldable: true, lead: true, folded: 'short lead line' });
    expect(postFold('a\nb\nc\nd').foldable).toBe(true);
    expect(postFold('a\nb\nc').foldable).toBe(false);
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('shift-click reads and hides the post; a plain click does nothing', async () => {
    const host = await mountBody(popout);
    post(host, 10).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: false }));
    await settle();
    expect(server.calls.some((c) => c.path.endsWith('/seen'))).toBe(false);
    expect(post(host, 10)).not.toBeNull();
    post(host, 10).querySelector('.tkm-post-text')!.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    await settle();
    expect(server.calls.filter((c) => c.path === '/cplugs/huddle/items/1/seen').map((c) => c.body)).toEqual([{ message: 10 }]);
    expect(host.querySelector('[data-task-manager-post="10"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-post="11"]')).not.toBeNull();
  });

  test('a long post is folded by default and its chevron opens and closes it inline', async () => {
    const host = await mountBody(popout);
    expect(post(host, 10).getAttribute('data-task-manager-post-folded')).toBeNull();
    expect(post(host, 10).querySelector('[data-task-manager-post-fold]')).toBeNull();
    const long = post(host, 11);
    expect(long.getAttribute('data-task-manager-post-folded')).toBe('true');
    expect(long.querySelector('.tkm-post-text')!.textContent!.length).toBeLessThan(LONG.length);
    long.querySelector<HTMLElement>('[data-task-manager-post-fold]')!.click();
    await settle();
    expect(post(host, 11).getAttribute('data-task-manager-post-folded')).toBe('false');
    expect(post(host, 11).querySelector('.tkm-post-text')!.textContent).toBe(LONG);
    expect(post(host, 11).querySelector('[data-task-manager-post-fold]')!.getAttribute('aria-expanded')).toBe('true');
    expect(server.calls.some((c) => c.path.endsWith('/seen'))).toBe(false);
    post(host, 11).querySelector<HTMLElement>('[data-task-manager-post-fold]')!.click();
    await settle();
    expect(post(host, 11).getAttribute('data-task-manager-post-folded')).toBe('true');
  });

  test('a post with a short first line shows the lead folded, the whole text opened', async () => {
    const host = await mountBody(popout);
    expect(post(host, 12).querySelector('.tkm-post-text')!.textContent).toBe('short lead line');
    post(host, 12).querySelector<HTMLElement>('[data-task-manager-post-fold]')!.click();
    await settle();
    expect(post(host, 12).querySelector('.tkm-post-text')!.textContent).toBe(LEAD);
  });
});
