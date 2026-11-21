/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: { hideCompleted: false } as Record<string, unknown> },
  body: null as unknown,
}));

const mk = (id: number, over: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...over,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle' && (init.method ?? 'GET') === 'PUT') {
        const body = JSON.parse(String(init.body));
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 2, open: 1, review: 0, questions: 0, claude_seq: 0 }] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        if (server.body) return structuredClone(server.body);
        return { list: 'all', revision: 7, cursor: 7, items: [mk(1, { text: 'a long description of the first item' }), mk(2, { state: 'done' })] };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
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
  server.body = null;
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  huddle.selected = 'all';
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the control row', () => {
  test('pop-out: one key row: remove completed on the left, then hide completed, then tell claude', async () => {
    const host = await mountBody(true);
    const row = host.querySelector<HTMLElement>('[data-task-manager-controls]')!;
    const order = [...row.querySelectorAll<HTMLElement>('[data-task-manager-remove-completed], [data-task-manager-hide-completed], [data-task-manager-send]')]
      .map((el) => Object.keys(el.dataset).find((k) => k.startsWith('taskManager'))!);
    expect(order).toEqual(['taskManagerRemoveCompleted', 'taskManagerHideCompleted', 'taskManagerSend']);
    expect(row.querySelector('.oc-chip')).toBeNull();
    for (const btn of row.querySelectorAll('button')) expect(btn.classList.contains('hd-key')).toBe(true);
  });

  test('pop-out: hide completed is a pressed toggle key and stores the setting', async () => {
    const host = await mountBody(true);
    const key = host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!;
    expect(key.classList.contains('hd-key')).toBe(true);
    expect(key.getAttribute('aria-label')).toBe('hide completed');
    expect(key.getAttribute('aria-pressed')).toBe('false');
    key.click();
    await settle();
    expect(key.getAttribute('aria-pressed')).toBe('true');
    expect(taskManagerPrefs.hideCompleted).toBe(true);
  });
});

describe('the pop-out foot (item 45)', () => {
  test('the pop-out ends in an empty foot strip under the add row; the sidebar has none', async () => {
    const pop = await mountBody(true);
    const foot = pop.querySelector<HTMLElement>('[data-task-manager-popout-foot]')!;
    expect(foot).not.toBeNull();
    expect(foot.textContent).toBe('');
    expect(foot.getAttribute('aria-hidden')).toBe('true');
    expect(foot.previousElementSibling?.classList.contains('hd-add')).toBe(true);
    expect(foot.parentElement?.lastElementChild).toBe(foot);
    unmount(app!);
    app = null;
    document.body.innerHTML = '';
    const side = await mountBody(false);
    expect(side.querySelector('[data-task-manager-popout-foot]')).toBeNull();
  });
});

describe('the add box and the open item', () => {
  test('the multiline box is at least four lines tall', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-multiline]')!.click();
    flushSync();
    const rows = Number(host.querySelector('textarea[data-task-manager-add]')!.getAttribute('rows'));
    expect(rows).toBeGreaterThanOrEqual(4);
  });

  test('an open item: the description is the first chat bubble under the status row, not inside the toggle', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    flushSync();
    const row = host.querySelector<HTMLElement>('[data-huddle-item="1"]')!;
    const head = row.querySelector<HTMLElement>('.tkm-head')!;
    const desc = row.querySelector<HTMLElement>('[data-task-manager-description="1"]')!;
    expect(desc.textContent).toBe('a long description of the first item');
    expect(head.contains(desc)).toBe(false);
    expect(head.querySelector('.tkm-status')).not.toBeNull();
    const detail = row.querySelector<HTMLElement>('[data-task-manager-detail="1"]')!;
    expect(detail.contains(desc)).toBe(true);
    expect(desc.closest('[data-task-manager-first="1"]')).not.toBeNull();
    const kids = [...row.children];
    expect(kids.indexOf(head)).toBeLessThan(kids.indexOf(detail));
    expect(row.classList.contains('tkm--open')).toBe(true);
    expect(head.getAttribute('aria-label')).toBe('a long description of the first item');
  });
  test('the open item at sidebar width: one content column, note, thread, then the reply last; the keys on the top line', async () => {
    server.body = { list: 'all', revision: 7, cursor: 7, items: [mk(1, { note: 'check the copy', thread: [
      { id: 5, item_id: 1, author: 'claude', kind: 'question', text: 'which one?', answered: false, created_at: 1_700_000_000, seq: 5 },
      { id: 6, item_id: 1, author: 'joe', kind: 'reply', text: 'the first', answered: false, created_at: 1_700_000_060, seq: 6 }] })] };
    await refreshTaskManager();
    server.prefs.settings.density = 'compact'; // a question opens the row only in compact (docs/task-manager.md section 24)
    await refreshPrefs();
    const host = document.createElement('div');
    host.style.width = '280px';
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    const row = host.querySelector<HTMLElement>('[data-huddle-item="1"]')!;
    const detail = row.querySelector<HTMLElement>('[data-task-manager-detail="1"]')!;
    expect([...row.children].filter((c) => !c.classList.contains('tkm-state')).map((c) => c.className.split(' ')[0]))
      .toEqual(['tkm-grip', 'oc-check', 'tkm-head', 'hdr-keys', 'tkm-detail']);
    const order = [...detail.querySelectorAll<HTMLElement>('[data-task-manager-note], [data-task-manager-message], [data-task-manager-actions]')]
      .map((el) => el.dataset.taskManagerNote ? 'note' : el.dataset.taskManagerMessage ? `msg${el.dataset.taskManagerMessage}` : 'actions');
    expect(order).toEqual(['note', 'msg5', 'msg6', 'actions']);
    for (const msg of detail.querySelectorAll('[data-task-manager-message]')) {
      expect([...msg.children].map((c) => c.className.split(' ')[0])).toEqual(['hb-head', 'hb-body']);
      expect(msg.querySelector('.hb-who')).not.toBeNull();
      expect(msg.querySelector('time.hb-time')?.textContent).toMatch(/^(\d\d-\d\d )?\d\d:\d\d$/);
    }
    const actions = detail.querySelector<HTMLElement>('[data-task-manager-actions="1"]')!;
    expect(actions.querySelector('[data-huddle-reply="1"]')).not.toBeNull();
    const keys = row.querySelector<HTMLElement>('[data-task-manager-keys="1"]')!;
    expect(keys.querySelector('[data-task-manager-note-open="1"]')).not.toBeNull();
    expect(keys.querySelector('[data-task-manager-delete="1"]')).not.toBeNull();
    expect(actions.querySelector('[data-task-manager-delete="1"]')).toBeNull();
  });

  test('an info item reads differently and the detail has no kind picker', async () => {
    server.body = { list: 'all', revision: 7, cursor: 7, items: [mk(1, { kind: 'info', created_by: 'claude' }), mk(2)] };
    await refreshTaskManager();
    const host = await mountBody();
    expect(host.querySelector('[data-huddle-item="1"]')?.classList.contains('tkm--info')).toBe(true);
    expect(host.querySelector('[data-huddle-item="2"]')?.classList.contains('tkm--info')).toBe(false);
    expect(host.querySelector('[data-huddle-kind]')).toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    flushSync();
    expect(host.querySelector('[data-huddle-kind-pick]')).toBeNull();
  });
});

describe('the add box names its target (Joe, 2026-10-12, huddle inbox 25)', () => {
  test('a chosen project reads add an item for "<project>"; all projects keeps the plain text', async () => {
    const host = await mountBody();
    huddle.lists = [{ key: '18', name: 'Carnivore' }, ...huddle.lists.filter((r) => r.key !== '18')] as typeof huddle.lists;
    huddle.addTarget = '18';
    flushSync();
    const input = () => host.querySelector<HTMLInputElement>('input[data-task-manager-add]')!;
    expect(input().placeholder).toBe('add an item for "Carnivore"');
    huddle.addTarget = 'all';
    flushSync();
    expect(input().placeholder).toBe('add an item for claude');
  });
});

