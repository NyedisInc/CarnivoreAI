/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, section: string, group: number | null) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group, status: section, section,
});

const server = vi.hoisted(() => ({
  view: 'status',
  calls: [] as { path: string; method: string; body: string }[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, method: init.method ?? 'GET', body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 3, settings: { hideCompleted: false, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: '12', name: 'alpha', project_id: 12, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 9, groups: [{
          list: '12', name: 'alpha', project_id: 12, revision: 20,
          groups: [{ id: 20, list: '12', name: 'ops', position: 0, folded: false }],
          items: [mk(1, 'review', 20), mk(2, 'review', null), mk(3, 'working', 20), mk(4, 'done', null)],
        }] };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, statusFolds } from './task-manager-status-folds.svelte';
import { AGGREGATE } from './huddle-model';
import { CASCADE_PATH, CHEVRON_PATH } from '../../lib/sidebar-shell/cascade-hint';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;
let writes = 0;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(view: string): Promise<HTMLElement> {
  server.view = view;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

beforeEach(() => {
  server.calls = [];
  statusFolds.choices = {};
  writes = 0;
  const real = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
    if (key === FOLDS_KEY) writes += 1;
    real.call(this, key, value);
  });
  try { localStorage.removeItem(FOLDS_KEY); } catch {  }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

function press(el: Element, shiftKey: boolean, keyboard = false): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, shiftKey, detail: keyboard ? 0 : 1 }));
}

const stored = (): Record<string, boolean> => JSON.parse(localStorage.getItem(FOLDS_KEY) as string);
const groupFolds = () => server.calls.filter((c) => c.path === '/cplugs/huddle/groups/fold');
const q = (host: HTMLElement, sel: string): Element => host.querySelector(sel) as Element;

describe('status view', () => {
  const UNDER = ['project/12', '12/review', '12/working', '12/done', 'status/20:review', 'status/12/none:review', 'status/20:working', 'status/12/none:done'];

  test('shift on a project bar shuts it and everything under it in one write, then opens it all in one more', async () => {
    const host = await mountBody('status');
    press(q(host, '[data-task-manager-project-fold="12"]'), true);
    await settle();
    expect(Object.keys(stored()).sort()).toEqual([...UNDER].sort());
    expect(Object.values(stored()).every((v) => v === true)).toBe(true);
    expect(writes).toBe(1);
    expect(q(host, '[data-task-manager-project-fold="12"]').getAttribute('aria-expanded')).toBe('false');
    press(q(host, '[data-task-manager-project-fold="12"]'), true);
    await settle();
    expect(Object.values(stored()).every((v) => v === false)).toBe(true);
    expect(writes).toBe(2);
    expect(host.querySelector('[data-task-manager-status-section="done"] [data-huddle-item]')).not.toBeNull();
  });

  test('shift on a status section reaches its area subsections only', async () => {
    const host = await mountBody('status');
    press(q(host, '[data-task-manager-status-fold="review"]'), true);
    await settle();
    expect(stored()).toEqual({ '12/review': true, 'status/20:review': true, 'status/12/none:review': true });
    expect(writes).toBe(1);
  });

  test('a plain click, and a plain Enter or Space, still toggle the one header', async () => {
    const host = await mountBody('status');
    press(q(host, '[data-task-manager-project-fold="12"]'), false);
    await settle();
    expect(stored()).toEqual({ 'project/12': true });
    press(q(host, '[data-task-manager-project-fold="12"]'), false, true);
    await settle();
    expect(stored()).toEqual({ 'project/12': false });
    press(q(host, '[data-task-manager-status-fold="review"]'), false);
    await settle();
    expect(stored()).toEqual({ 'project/12': false, '12/review': true });
  });

  test('Shift+Enter and Shift+Space (a keyboard click carrying Shift) take the cascade path', async () => {
    const host = await mountBody('status');
    press(q(host, '[data-task-manager-status-fold="review"]'), true, true);
    await settle();
    expect(Object.keys(stored()).sort()).toEqual(['12/review', 'status/12/none:review', 'status/20:review']);
  });
});

describe('area view', () => {
  test('shift on a group header folds the group and its status subsections: one request, one write', async () => {
    const host = await mountBody('area');
    press(q(host, '[data-task-manager-fold="20"]'), true);
    await settle();
    expect(groupFolds().map((c) => JSON.parse(c.body))).toEqual([{ ids: [20], folded: true }]);
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/groups/20')).toBe(false);
    expect(stored()).toEqual({ '20:review': true, '20:working': true });
    expect(writes).toBe(1);
  });

  test('shift on a project bar folds its groups and every subsection, ungrouped ones included', async () => {
    const host = await mountBody('area');
    press(q(host, '[data-task-manager-project-fold="12"]'), true);
    await settle();
    expect(groupFolds().map((c) => JSON.parse(c.body))).toEqual([{ ids: [20], folded: true }]);
    expect(Object.keys(stored()).sort()).toEqual(['20:review', '20:working', 'none:done', 'none:review', 'project/12']);
    expect(writes).toBe(1);
  });

  test('a plain click on a group header sends the one group\'s own fold and nothing else', async () => {
    const host = await mountBody('area');
    press(q(host, '[data-task-manager-fold="20"]'), false);
    await settle();
    expect(server.calls.filter((c) => c.path === '/cplugs/huddle/groups/20').map((c) => JSON.parse(c.body))).toEqual([{ folded: true }]);
    expect(groupFolds()).toEqual([]);
    expect(writes).toBe(0);
  });
});

function mouseDown(el: Element, shiftKey: boolean): boolean {
  const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true, shiftKey, detail: 1 });
  el.dispatchEvent(down);
  return !down.defaultPrevented;
}

describe('Shift+press on a fold header never starts a text selection (the left menu does the same)', () => {
  test('status view: project bar, status section and area subsection', async () => {
    const host = await mountBody('status');
    for (const sel of ['[data-task-manager-project-fold="12"]', '[data-task-manager-status-fold="review"]', '[data-task-manager-area-sub-fold]']) {
      expect(mouseDown(q(host, sel), true), sel).toBe(false);
      expect(mouseDown(q(host, sel), false), `${sel} plain`).toBe(true);
    }
  });

  test('area view: group header and status subsection', async () => {
    const host = await mountBody('area');
    for (const sel of ['[data-task-manager-fold="20"]', '[data-task-manager-area-sub-fold]']) {
      expect(mouseDown(q(host, sel), true), sel).toBe(false);
      expect(mouseDown(q(host, sel), false), `${sel} plain`).toBe(true);
    }
  });
});

describe('the left menu\'s shift cue: the arrow turns into the double arrow while Shift is held over a cascading header', () => {
  const pathOf = (btn: Element): string => (btn.querySelector('.session-sidebar-group__chevron path') as Element).getAttribute('d') as string;
  const shiftKey = (type: 'keydown' | 'keyup', shift: boolean): void => {
    window.dispatchEvent(new KeyboardEvent(type, { shiftKey: shift, bubbles: true }));
  };

  async function cueAt(view: string, sel: string): Promise<void> {
    const host = await mountBody(view);
    const btn = q(host, sel);
    expect(pathOf(btn)).toBe(CHEVRON_PATH);
    btn.dispatchEvent(new Event('pointerenter'));
    shiftKey('keydown', true);
    expect(pathOf(btn)).toBe(CASCADE_PATH);
    shiftKey('keyup', false);
    expect(pathOf(btn)).toBe(CHEVRON_PATH);
    shiftKey('keydown', true);
    expect(pathOf(btn)).toBe(CASCADE_PATH);
    window.dispatchEvent(new Event('blur'));
    expect(pathOf(btn)).toBe(CHEVRON_PATH);
    shiftKey('keydown', true);
    btn.dispatchEvent(new Event('pointerleave'));
    expect(pathOf(btn)).toBe(CHEVRON_PATH);
    shiftKey('keyup', false);
  }

  test('project bar', () => cueAt('status', '[data-task-manager-project-fold="12"]'));
  test('status section', () => cueAt('status', '[data-task-manager-status-fold="review"]'));
  test('group header (area view)', () => cueAt('area', '[data-task-manager-fold="20"]'));
});
