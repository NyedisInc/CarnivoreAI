/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

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

describe('move to another list', () => {
  test('the open item offers every other list and posts the move to the chosen one', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-move-open="1"]')!.click();
    await settle();
    const options = [...host.querySelectorAll<HTMLElement>('[data-task-manager-move-to]')].map((o) => o.dataset.taskManagerMoveTo);
    expect(options).toEqual(['12', '18']);
    host.querySelector<HTMLElement>('[data-task-manager-move-to="18"]')!.click();
    await settle();
    const move = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/move');
    expect(move?.method).toBe('POST');
    expect(JSON.parse(move!.body)).toEqual({ list: '18' });
    expect(host.querySelector('[data-task-manager-move-pick]')).toBeNull();
  });

  for (const popout of [false, true]) {
    test(`${popout ? 'pop-out' : 'sidebar'}: the menu stays inside the huddle panel (so it inherits the panel theme) and wears the shared popup look`, async () => {
      const host = await mountBody(popout);
      host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
      await settle();
      host.querySelector<HTMLElement>('[data-task-manager-move-open="1"]')!.click();
      await settle();
      const menu = host.querySelector<HTMLElement>('[data-task-manager-move-pick="1"]')!;
      expect(menu, 'rendered under the mounted panel, not portalled to body').not.toBeNull();
      expect(menu.closest('[data-task-manager-body]')).not.toBeNull();
      expect(menu.classList.contains('popup-focus')).toBe(true);
    });
  }

  test('the picker is a menu: its own list is marked and not a choice, arrows walk the rows, Escape closes and returns focus', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    const key = host.querySelector<HTMLElement>('[data-task-manager-move-open="1"]')!;
    key.click();
    await settle();
    const menu = host.querySelector<HTMLElement>('[data-task-manager-move-pick="1"]')!;
    expect(menu.getAttribute('role')).toBe('menu');
    const here = menu.querySelector<HTMLButtonElement>('[data-task-manager-move-here]')!;
    expect(here.getAttribute('aria-checked')).toBe('true');
    expect(here.disabled).toBe(true);
    const rows = [...menu.querySelectorAll<HTMLElement>('[role="menuitemradio"]')];
    expect(rows.length).toBe(3);
    const enabled = [...menu.querySelectorAll<HTMLElement>('[role^="menuitem"]')].filter((r) => !(r as HTMLButtonElement).disabled);
    expect(document.activeElement).toBe(enabled[0]);
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(enabled[1]);
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(enabled[2]);
    for (let i = 3; i < enabled.length; i += 1) {
      menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      expect(document.activeElement).toBe(enabled[i]);
    }
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(enabled[0]);
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(host.querySelector('[data-task-manager-move-pick]')).toBeNull();
    expect(document.activeElement).toBe(key);
  });

  test('a press outside the menu closes it without moving', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-move-open="1"]')!.click();
    await settle();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    await settle();
    expect(host.querySelector('[data-task-manager-move-pick]')).toBeNull();
    expect(server.calls.some((c) => /\/move$/.test(c.path))).toBe(false);
  });
});
