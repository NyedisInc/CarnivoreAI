/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as { path: string; method: string; body: string }[], view: 'area' }));

const mk = (id: number, group: number | null) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', status: 'open', section: 'open',
  number: null, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group,
});
const GROUPS = [
  { id: 5, list: '12', name: 'early-empty', position: 0, folded: false },
  { id: 7, list: '12', name: 'auth', position: 1, folded: false },
  { id: 8, list: '12', name: 'late-empty', position: 2, folded: false },
];
const ITEMS = [mk(1, null), mk(2, 7), mk(3, 7)];

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, showEmptyGroups: true, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'carnivore', project_id: 12, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 1, groups: [] };
      if (path === '/cplugs/huddle/lists/12?live_only=1') return { list: '12', revision: 1, cursor: 1, groups: GROUPS, items: ITEMS };
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
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout: boolean): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

function layOut(host: HTMLElement): void {
  const boxes = new Map<Element, { top: number; bottom: number }>();
  let y = 0;
  for (const el of host.querySelectorAll('[data-task-manager-section-head], [data-task-manager-status-head], [data-task-manager-section], [data-task-manager-status-section], [data-task-manager-area-drop], [data-huddle-item], [data-task-manager-group-empty]')) {
    if (el.hasAttribute('data-task-manager-section') || el.hasAttribute('data-task-manager-status-section')) {
      const top = y;
      const rows = el.querySelectorAll('[data-huddle-item], [data-task-manager-group-empty]').length;
      boxes.set(el, { top, bottom: top + rows * 20 });
      continue;
    }
    boxes.set(el, { top: y, bottom: y + 20 });
    y += 20;
  }
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    const b = boxes.get(this) ?? { top: 0, bottom: 0 };
    return { top: b.top, bottom: b.bottom, height: b.bottom - b.top, left: 0, right: 100, width: 100, x: 0, y: b.top, toJSON: () => ({}) } as DOMRect;
  });
}

const sectionKeys = (host: HTMLElement): (string | undefined)[] =>
  [...host.querySelectorAll<HTMLElement>('[data-task-manager-section]')].map((s) => s.dataset.taskManagerSection);
const press = (el: Element, type: string, y: number): void => {
  el.dispatchEvent(new MouseEvent(type, { button: 0, clientY: y, bubbles: true }));
  flushSync();
};

beforeEach(async () => {
  server.calls = [];
  server.view = 'area';
  huddle.selected = '12';
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('by area, empty groups are always drawn and are drop targets while a row is dragged', () => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';

    test(`${where}: shown at rest, in group order, each with its empty line and remove key`, async () => {
      expect(taskManagerPrefs.view).toBe('area');
      const host = await mountBody(popout);
      expect(sectionKeys(host)).toEqual(['none', '5', '7', '8']);
      expect(host.querySelector('[data-task-manager-section-head="5"]')).not.toBeNull();
      expect(host.querySelector('[data-task-manager-section-head="8"]')).not.toBeNull();
      expect(host.querySelectorAll('[data-task-manager-group-empty]').length).toBe(2);
      expect(host.querySelector('[data-task-manager-group-remove="5"]')).not.toBeNull();
    });

    test(`${where}: a drag keeps them drawn, and they stay after the release`, async () => {
      const host = await mountBody(popout);
      const grip = host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')!;
      press(grip, 'pointerdown', 10);
      expect(sectionKeys(host)).toEqual(['none', '5', '7', '8']);
      expect(host.querySelectorAll('[data-task-manager-group-empty]').length).toBe(2);
      press(grip, 'pointerup', 10);
      expect(sectionKeys(host)).toEqual(['none', '5', '7', '8']);
      expect(host.querySelectorAll('[data-task-manager-group-empty]').length).toBe(2);
    });

    test(`${where}: a drop onto an empty area files the row there and lights that area while hovered`, async () => {
      const host = await mountBody(popout);
      const grip = host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')!;
      press(grip, 'pointerdown', 10);
      layOut(host);
      const line = host.querySelector<HTMLElement>('[data-task-manager-group-empty="8"]')!;
      const lineTop = (line as HTMLElement).getBoundingClientRect().top;
      press(grip, 'pointermove', lineTop + 5);
      expect(line.classList.contains('hds-empty--target')).toBe(true);
      expect(host.querySelector('[data-task-manager-group-empty="5"]')!.classList.contains('hds-empty--target')).toBe(false);
      press(grip, 'pointerup', lineTop + 5);
      await settle();
      const sent = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/group');
      expect(sent && JSON.parse(sent.body)).toEqual({ group: 8, index: 0, expected_revision: 1 });
    });
  }
});

describe('in the status view, a drag lights area headers as drop targets', () => {
  for (const popout of [false, true]) {
    test(`${popout ? 'pop-out' : 'sidebar'}: targets only during the drag (no strip of list items); releasing over one files the row`, async () => {
      server.view = 'status';
      await refreshPrefs();
      expect(taskManagerPrefs.view).toBe('status');
      const host = await mountBody(popout);
      expect(host.querySelector('[data-task-manager-area-drop]')).toBeNull();
      const grip = host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')!;
      press(grip, 'pointerdown', 10);
      const targets = [...host.querySelectorAll<HTMLElement>('[data-task-manager-area-drop]')].map((e) => e.dataset.taskManagerAreaDrop);
      expect(targets).toEqual(['7', 'none', '5', '8']);
      expect(host.querySelector('[data-huddle-area-drops], .hss-areas, .hss-area')).toBeNull();
      layOut(host);
      const over = host.querySelector<HTMLElement>('[data-task-manager-area-drop="7"]')!;
      const top = over.getBoundingClientRect().top;
      press(grip, 'pointermove', top + 5);
      expect(over.classList.contains('hds-sub--over')).toBe(true);
      press(grip, 'pointerup', top + 5);
      expect(host.querySelector('[data-task-manager-area-drop]')).toBeNull();
      await settle();
      const sent = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/group');
      expect(sent && JSON.parse(sent.body)).toEqual({ group: 7, expected_revision: 1 });
      expect(server.calls.some((c) => c.method === 'PUT' && c.path.endsWith('/order'))).toBe(false);
    });
  }
});
