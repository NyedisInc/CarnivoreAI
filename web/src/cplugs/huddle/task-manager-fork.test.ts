/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { menuNode, openRowMenu } from './row-menu-driver.test.helper';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: null, revision: 3, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', ...extra,
});

const server = vi.hoisted(() => ({ items: [] as unknown[], posts: [] as { path: string; body: Record<string, unknown> }[], refuse: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'POST' && /\/fork$/.test(path)) {
        server.posts.push({ path, body: JSON.parse(String(init.body)) as Record<string, unknown> });
        if (server.refuse) throw Object.assign(new Error('refused'), { status: 400, body: { code: 'task_manager_invalid', detail: 'no' } });
        return {};
      }
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 3 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 9, cursor: 9, groups: [], items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FORK_STATES, forkBody, forkDraft } from './task-manager-fork';
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
  server.posts = [];
  server.refuse = false;
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = [mk(1, { title: 'Parent one' }), mk(2, { forked_from: 1, forked_from_title: 'Parent one' }), mk(3, { forked_from: 99, forked_from_title: 'Gone parent' })];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the request body', () => {
  test('an untouched draft forks a plain copy and offers every state the owner may set', () => {
    const item = { title: 'Parent one' };
    expect(forkBody(item, forkDraft(item))).toEqual({});
    expect(FORK_STATES).toContain('done');
  });

  test('only what changed is sent: a new title, the fork state, the original state', () => {
    const item = { title: 'Parent one' };
    expect(forkBody(item, { title: ' Piece ', forkState: 'done', parentState: 'todo' })).toEqual({ title: 'Piece', fork_state: 'done', parent_state: 'todo' });
    expect(forkBody(item, { title: 'Parent one', forkState: 'open', parentState: 'review' })).toEqual({ parent_state: 'review' });
    expect(forkBody({ title: null }, { title: '', forkState: 'review', parentState: '' })).toEqual({ fork_state: 'review' });
  });
});

describe('the dialog', () => {
  async function openDialog(host: HTMLElement): Promise<void> {
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    openRowMenu(host, 1);
    await settle();
    const entry = menuNode('fork')!;
    expect(entry.textContent).toContain('fork...');
    entry.click();
    await settle();
  }

  test('the item menu opens it, and fork posts one request with the picked states, then closes', async () => {
    const host = await mountBody();
    await openDialog(host);
    const dialog = host.querySelector<HTMLElement>('[data-task-manager-fork-dialog="1"]');
    expect(dialog, 'the dialog opens').not.toBeNull();
    const title = dialog!.querySelector<HTMLInputElement>('[data-task-manager-fork-title]')!;
    expect(title.value).toBe('Parent one');
    const forkState = dialog!.querySelector<HTMLSelectElement>('[data-task-manager-fork-state]')!;
    const parentState = dialog!.querySelector<HTMLSelectElement>('[data-task-manager-fork-parent-state]')!;
    expect([...forkState.options].map((o) => o.value)).toEqual([...FORK_STATES]);
    expect([...parentState.options].map((o) => o.value)).toEqual(['', ...FORK_STATES]);
    forkState.value = 'done';
    forkState.dispatchEvent(new Event('change', { bubbles: true }));
    parentState.value = 'todo';
    parentState.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    dialog!.querySelector<HTMLElement>('[data-task-manager-fork-save]')!.click();
    await settle();
    expect(server.posts).toEqual([{ path: '/cplugs/huddle/items/1/fork', body: { fork_state: 'done', parent_state: 'todo' } }]);
    expect(host.querySelector('[data-task-manager-fork-dialog]'), 'it closes once the server took it').toBeNull();
  });

  test('a refusal leaves the dialog open and cancel closes it without a request', async () => {
    const host = await mountBody();
    await openDialog(host);
    server.refuse = true;
    host.querySelector<HTMLElement>('[data-task-manager-fork-save]')!.click();
    await settle();
    expect(server.posts).toHaveLength(1);
    expect(host.querySelector('[data-task-manager-fork-dialog]')).not.toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-fork-close]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-fork-dialog]')).toBeNull();
    expect(server.posts).toHaveLength(1);
  });
});

describe('the from link', () => {
  test('a fork shows "from <parent title>" that opens the parent; a plain item shows none', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-forked="1"]')).toBeNull();
    const link = host.querySelector<HTMLElement>('[data-task-manager-forked-open="2"]')!;
    expect(link.textContent).toBe('from Parent one');
    expect(huddle.openId).toBeNull();
    link.click();
    await settle();
    expect(huddle.openId).toBe(1);
  });

  test('a parent that is not on screen reads as plain text, not a link', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-forked-open="3"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-forked="3"]')!.textContent).toContain('from Gone parent');
  });

  test('the open fork keeps the line at the top of its detail', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-detail="2"] [data-task-manager-forked="2"]')).not.toBeNull();
  });
});
