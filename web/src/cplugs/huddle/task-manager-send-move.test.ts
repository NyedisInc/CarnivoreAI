/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { closeItemMenu } from '../../lib/item-menu/open.svelte';
import { menuNode, menuNodeIds, openRowMenu, openRowMenuByKey } from './row-menu-driver.test.helper';

const server = vi.hoisted(() => ({
  untold: { all: true, '12': false } as Record<string, boolean>,
  calls: [] as { path: string; method: string; body: string }[],
}));

const mk = (id: number) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0, untold: server.untold.all, waiting_to_send: 2 },
          { key: '12', name: 'carnivore', project_id: 12, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0, untold: server.untold['12'] },
          { key: '18', name: 'CloudeCode', project_id: 18, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0, untold: false },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [{ id: 'ses_a', label: 'agent a', project: 'carnivore' }], default: 'ses_a', reason: 'last_task_manager_caller' };
      if (path === '/cplugs/huddle/send') {
        const lists = (JSON.parse(String(init.body)) as { lists: string[] }).lists;
        for (const list of lists) server.untold[list as 'all' | '12'] = false;
        return { results: lists.map((list) => ({ list, status: 'sent', target: 'ses_a', label: 'agent a' })) };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: [mk(1), mk(2)] };
      if (/^\/cplugs\/huddle\/aggregate$/.test(path)) return { cursor: 7, groups: [{ list: 'all', name: null, project_id: null, revision: 7, items: [mk(1), mk(2)] }] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { moveTargets } from './huddle-model';
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

async function mountBody(popout = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

beforeEach(async () => {
  server.untold = { all: true, '12': false };
  server.calls = [];
  huddle.selected = 'all';
  huddle.openId = null;
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('moveTargets', () => {
  test('an item moves to every real list except its own', () => {
    expect(moveTargets([{ key: 'all' }, { key: '12' }, { key: '18' }], '12').map((r) => r.key)).toEqual(['all', '18']);
  });
});

describe('the send button', () => {
  test('enabled with a count badge and tooltip while changes wait', async () => {
    const host = await mountBody(false);
    const button = host.querySelector<HTMLButtonElement>('[data-task-manager-send]')!;
    expect(button.disabled).toBe(false);
    expect(button.querySelector('[data-task-manager-send-badge]')?.textContent).toBe('2');
    expect(button.getAttribute('aria-label')).toBe('send to carnivore: 2 changes waiting');
    expect(button.getAttribute('title')).toBe('send to carnivore: 2 changes waiting');
    expect(button.querySelector('[data-huddle-key-label]')).toBeNull();
  });

  test('disabled with no badge when nothing waits', async () => {
    huddle.selected = '12';
    await refreshTaskManager();
    const host = await mountBody(false);
    const button = host.querySelector<HTMLButtonElement>('[data-task-manager-send]')!;
    expect(button.disabled).toBe(true);
    expect(button.querySelector('[data-task-manager-send-badge]')).toBeNull();
    expect(button.getAttribute('title')).toBe('nothing waiting to send');
  });

  for (const popout of [false, true]) {
    test(`${popout ? 'pop-out label' : 'sidebar icon'} wears no untold accent and still tells the list`, async () => {
      const host = await mountBody(popout);
      const button = (): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-send]')!;
      expect(button().getAttribute('data-huddle-untold')).toBeNull();
      expect(button().classList.contains('hdtl--untold')).toBe(false);
      host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
      await settle();
      expect(server.calls.some((c) => c.path === '/cplugs/huddle/send' && c.method === 'POST')).toBe(true);
    });
  }
});

describe('move to another list (the row menu, #2567)', () => {
  test('a row draws no menu button; the menu is its right click and Shift+F10', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-move-open]')).toBeNull();
    expect(host.querySelector('[data-huddle-item="1"] [aria-haspopup="menu"]')).toBeNull();
    openRowMenu(host, 1);
    const fromClick = menuNodeIds();
    expect(fromClick).toContain('move-to');
    closeItemMenu();
    flushSync();
    expect(menuNodeIds()).toEqual([]);
    openRowMenuByKey(host, 1);
    expect(menuNodeIds()).toEqual(fromClick);
  });

  test('move to offers every other list and posts the move to the chosen one', async () => {
    const host = await mountBody();
    openRowMenu(host, 1);
    menuNode('move-to')!.click();
    flushSync();
    const lists = menuNodeIds().filter((id) => id.startsWith('move-to:'));
    expect(lists).toEqual(['move-to:all', 'move-to:12', 'move-to:18']);
    expect(menuNode('move-to:all')!.getAttribute('aria-checked')).toBe('true');
    menuNode('move-to:18')!.click();
    await settle();
    const move = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/move');
    expect(move?.method).toBe('POST');
    expect(JSON.parse(move!.body)).toEqual({ list: '18' });
    expect(menuNodeIds()).toEqual([]);
  });

  test('the item\'s own list is not a choice: it posts nothing', async () => {
    const host = await mountBody();
    openRowMenu(host, 1);
    menuNode('move-to')!.click();
    flushSync();
    menuNode('move-to:all')!.click();
    await settle();
    expect(server.calls.some((c) => /\/(move|group)$/.test(c.path))).toBe(false);
  });
});
