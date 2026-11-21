/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[], inbox: [] as unknown[], posts: [] as { path: string; body: string }[], queued: true, fail: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'POST' && /\/inbox\/\d+\/nudge$/.test(path)) {
        if (server.fail) throw Object.assign(new Error('refused'), { status: 400 });
        server.posts.push({ path, body: String(init.body ?? '') });
        return { entry: null, sent: true };
      }
      if (init?.method === 'POST' && /\/inbox$/.test(path)) {
        if (server.fail) throw Object.assign(new Error('refused'), { status: 400 });
        server.posts.push({ path, body: String(init.body) });
        return { queued: server.queued, entry: null, item: null };
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0 }] };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 9, cursor: 9, groups: [], items: server.items, ...(server.inbox.length ? { inbox: server.inbox } : {}) };
      return {};
    },
  };
});

import { addItem, huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
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

beforeEach(() => {
  huddle.selected = 'all';
  huddle.addTarget = '12';
  huddle.openId = null;
  server.posts = [];
  server.queued = true;
  server.fail = false;
  server.inbox = [];
  server.items = [mk(1), mk(2, { from_inbox: { id: 5, text: 'backlog dark mode\nand fix login' } })];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

describe('a pending add box entry', () => {
  test('shows at the top of the list as a filing row with the text as typed, and nothing when none is open', async () => {
    let host = await mountBody();
    expect(host.querySelector('[data-task-manager-inbox]')).toBeNull();
    unmount(app!);
    app = null;
    server.inbox = [{ id: 5, text: 'backlog dark mode', status: 'filing', created_at: 1 }, { id: 6, text: 'fix login', status: 'queued', created_at: 2 }];
    host = await mountBody();
    const rows = [...host.querySelectorAll<HTMLElement>('[data-task-manager-inbox]')];
    expect(rows.map((r) => r.dataset.taskManagerInbox)).toEqual(['5', '6']);
    expect(rows[0]!.textContent).toContain('filing...');
    expect(rows[0]!.querySelector('[data-task-manager-inbox-text]')!.textContent).toBe('backlog dark mode');
    expect(rows[1]!.textContent).toContain('queued');
  });
});

describe('the nudge key on a nobody filed entry (issue #1848)', () => {
  test('only a stuck entry has the key, and pressing it posts to that entry nudge route once', async () => {
    server.inbox = [{ id: 5, text: 'a', status: 'stuck', created_at: 1 }, { id: 6, text: 'b', status: 'filing', created_at: 2 }, { id: 7, text: 'c', status: 'queued', created_at: 3 }];
    const host = await mountBody();
    expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-inbox-nudge]')].map((b) => b.dataset.taskManagerInboxNudge)).toEqual(['5']);
    const key = host.querySelector<HTMLButtonElement>('[data-task-manager-inbox-nudge="5"]')!;
    expect(key.getAttribute('aria-label')).toBe('send this entry to a session again');
    key.click();
    key.click();
    await settle();
    expect(server.posts.map((p) => p.path)).toEqual(['/cplugs/huddle/inbox/5/nudge']);
  });

  test('a refused nudge puts the reason in the notice and leaves the key usable', async () => {
    server.inbox = [{ id: 5, text: 'a', status: 'stuck', created_at: 1 }];
    const host = await mountBody();
    server.fail = true;
    host.querySelector<HTMLButtonElement>('[data-task-manager-inbox-nudge="5"]')!.click();
    await settle();
    expect(huddle.notice).not.toBe('');
    expect(host.querySelector<HTMLButtonElement>('[data-task-manager-inbox-nudge="5"]')!.disabled).toBe(false);
  });
});

describe('the from the add box line', () => {
  test('an item filed from an entry shows the original text; any other item shows none', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-from-inbox="1"]')).toBeNull();
    const line = host.querySelector('[data-task-manager-from-inbox="2"]')!;
    expect(line.textContent).toContain('from the add box');
    expect(line.querySelector('[data-task-manager-from-inbox-text]')!.textContent).toBe('backlog dark mode\nand fix login');
  });
});

describe('the author icon of an item typed into the add box (Joe (ccsliinc), 2026-10-12, issue #1720)', () => {
  test('filed from the entry itself: the person; carrying the link only (a task claude made, #1703) or none: claude', async () => {
    server.items = [
      mk(1),
      mk(3, { from_inbox: { id: 5, text: 'fix login', direct: true } }),
      mk(4, { from_inbox: { id: 5, text: 'fix login', direct: false } }),
    ];
    const host = await mountBody();
    const row = (id: number): HTMLElement => host.querySelector<HTMLElement>(`[data-huddle-item="${id}"]`)!;
    expect(row(3).querySelector('[data-task-manager-by-joe]')).not.toBeNull();
    expect(row(3).querySelector('[data-task-manager-by-claude]')).toBeNull();
    expect(row(4).querySelector('[data-task-manager-by-claude]')).not.toBeNull();
    expect(row(1).querySelector('[data-task-manager-by-claude]')).not.toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    expect(host.querySelector<HTMLElement>('[data-task-manager-first="3"]')!.dataset.by).toBe('joe');
  });
});

describe('the add box write', () => {
  test('posts a multi-line paste to the add target inbox as ONE call with the text whole, and reports queued (R55)', async () => {
    expect(await addItem('backlog a\nnow b\n\nand c')).toBe('queued');
    expect(server.posts.map((p) => [p.path, JSON.parse(p.body)])).toEqual([
      ['/cplugs/huddle/lists/12/inbox', { text: 'backlog a\nnow b\n\nand c', client_id: expect.any(String) }]]);
  });

  test('reports added when the server added the item at once (switch off), and failed on a refusal', async () => {
    server.queued = false;
    expect(await addItem('plain')).toBe('added');
    server.fail = true;
    expect(await addItem('x')).toBe('failed');
  });
});
