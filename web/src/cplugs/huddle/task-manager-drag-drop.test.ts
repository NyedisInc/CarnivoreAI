/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { GHOST_GUTTER } from './task-manager-ghost';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as { path: string; method: string; body: string }[], view: 'area' }));

const mk = (id: number, group: number | null) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', status: 'open', section: 'open',
  number: null, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group,
});
// Area 7 holds rows; areas 8 (before it in nothing, after it by place) and 5 (placed FIRST) are empty.
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

/** Lay every section, status section and area target out top to bottom, 20px a line (jsdom has no layout). */
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


const at = (el: Element | Window, type: string, y: number, x = 10): void => {
  el.dispatchEvent(new MouseEvent(type, { button: 0, clientX: x, clientY: y, bubbles: true }));
  flushSync();
};
const escape = (): void => {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
};
const ghost = (): HTMLElement | null => document.body.querySelector<HTMLElement>('[data-task-manager-ghost]');
const writes = (): string[] => server.calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.path}`);

beforeEach(async () => {
  server.calls = [];
  huddle.selected = '12';
  huddle.openId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

function rowMiddle(host: HTMLElement, id: number): number {
  layOut(host);
  const r = host.querySelector(`[data-huddle-item="${id}"]`)!.getBoundingClientRect();
  vi.restoreAllMocks();
  return (r.top + r.bottom) / 2;
}

async function grab(view: string, popout: boolean, id = 1): Promise<{ host: HTMLElement; grip: HTMLElement; pressY: number }> {
  server.view = view;
  await refreshPrefs();
  await refreshTaskManager();
  const host = await mountBody(popout);
  const grip = host.querySelector<HTMLElement>(`[data-task-manager-grip="${id}"]`)!;
  const pressY = rowMiddle(host, id);
  at(grip, 'pointerdown', pressY);
  layOut(host);
  return { host, grip, pressY };
}

const target = (host: HTMLElement, area: string): HTMLElement => host.querySelector<HTMLElement>(`[data-task-manager-area-drop="${area}"]`)!;

describe.each([['by area', 'area', '8'], ['by status', 'status', '7']])('%s', (_name, view, area) => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';

    test(`${where}: the ghost follows the pointer over a dimmed placeholder and is gone after the drop`, async () => {
      const { host, grip, pressY } = await grab(view, popout);
      const copy = ghost()!;
      expect(copy).not.toBeNull();
      expect(copy.textContent).toContain('item 1');
      expect(copy.classList.contains('tkm--lifted')).toBe(true);
      expect(copy.style.position).toBe('fixed');
      expect(copy.style.pointerEvents).toBe('none');
      // and the real
      expect(host.querySelectorAll('[data-huddle-item="1"]').length).toBe(1);
      expect(copy.hasAttribute('data-huddle-item') || copy.querySelector('[data-huddle-item]')).toBeFalsy();
      expect(host.querySelector('[data-huddle-item="1"]')!.classList.contains('tkm--placeholder')).toBe(true);
      at(grip, 'pointermove', 90, 40);
      expect(copy.style.transform).toBe(`translate(${30 + GHOST_GUTTER}px, ${90 - pressY}px)`);
      at(grip, 'pointerup', 90, 40);
      expect(ghost()).toBeNull();
      expect(host.querySelector('[data-huddle-item="1"]')!.classList.contains('tkm--placeholder')).toBe(false);
    });

    test(`${where}: dropping on an area header moves the row there, and the header lights while hovered`, async () => {
      const { host, grip } = await grab(view, popout);
      const header = target(host, area);
      const top = header.getBoundingClientRect().top;
      expect(header.classList.contains('hds-sub--over') || header.classList.contains('hds-head--target')).toBe(false);
      at(grip, 'pointermove', top + 5);
      expect(header.classList.contains('hds-sub--over') || header.classList.contains('hds-head--target')).toBe(true);
      at(grip, 'pointerup', top + 5);
      await settle();
      const sent = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/group');
      expect(sent && JSON.parse(sent.body)).toMatchObject({ group: Number(area) });
      expect(ghost()).toBeNull();
    });

    test(`${where}: Escape cancels: the row snaps back and nothing is written`, async () => {
      const { host, grip } = await grab(view, popout);
      const top = target(host, area).getBoundingClientRect().top;
      at(grip, 'pointermove', top + 5);
      expect(ghost()).not.toBeNull();
      escape();
      expect(ghost()).toBeNull();
      expect(host.querySelector('[data-huddle-item="1"]')!.classList.contains('tkm--placeholder')).toBe(false);
      expect(host.querySelector('[data-task-manager-area-drop]')).toBeNull();
      at(grip, 'pointerup', top + 5);
      await settle();
      expect(writes()).toEqual([]);
    });

    test(`${where}: dropping where there is no target cancels: nothing is written`, async () => {
      const { grip } = await grab(view, popout);
      at(grip, 'pointermove', 5000);
      expect(ghost()).not.toBeNull();
      at(grip, 'pointerup', 5000);
      await settle();
      expect(ghost()).toBeNull();
      expect(writes()).toEqual([]);
    });

    test(`${where}: a pointer cancel (a touch interrupted) ends it like Escape`, async () => {
      const { host, grip } = await grab(view, popout);
      const top = target(host, area).getBoundingClientRect().top;
      at(grip, 'pointermove', top + 5);
      at(grip, 'pointercancel', top + 5);
      await settle();
      expect(ghost()).toBeNull();
      expect(writes()).toEqual([]);
    });
  }
});

describe.each([['by area', 'area'], ['by status', 'status']])('%s: reordering inside a list', (_name, view) => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';
    const lines = (host: HTMLElement): number => host.querySelectorAll('.hd-drop, .hss-drop').length;

    test(`${where}: dragging over rows shows one insertion line, and the drop sets the position through the order route`, async () => {
      const { host, grip } = await grab(view, popout, 3);
      const first = host.querySelector('[data-huddle-item="2"]')!.getBoundingClientRect();
      expect(lines(host)).toBe(0);
      at(grip, 'pointermove', first.top + 2);
      expect(lines(host)).toBe(1);
      expect(host.querySelector('[data-huddle-item="2"]')!.previousElementSibling?.matches('.hd-drop, .hss-drop')).toBe(true);
      at(grip, 'pointerup', first.top + 2);
      await settle();
      const order = server.calls.find((c) => c.method === 'PUT' && c.path === '/cplugs/huddle/lists/12/order');
      expect(order).toBeTruthy();
      const ids: number[] = JSON.parse(order!.body).ids;
      expect(ids.indexOf(3)).toBeLessThan(ids.indexOf(2));
      expect(server.calls.some((c) => c.path.endsWith('/group'))).toBe(false);
      expect(ghost()).toBeNull();
    });

    test(`${where}: Escape while an insertion line shows writes nothing`, async () => {
      const { host, grip } = await grab(view, popout, 3);
      at(grip, 'pointermove', host.querySelector('[data-huddle-item="2"]')!.getBoundingClientRect().top + 2);
      expect(lines(host)).toBe(1);
      escape();
      expect(lines(host)).toBe(0);
      at(grip, 'pointerup', 0);
      await settle();
      expect(writes()).toEqual([]);
    });
  }
});

describe('by status: dropping among another area\'s rows of the same section', () => {
  for (const popout of [false, true]) {
    const where = popout ? 'pop-out' : 'sidebar';
    test(`${where}: the line shows before that row and the drop files the row in that area at that place`, async () => {
      const { host, grip } = await grab('status', popout, 1);
      const row2 = host.querySelector('[data-huddle-item="2"]')!;
      at(grip, 'pointermove', row2.getBoundingClientRect().top + 2);
      expect(host.querySelectorAll('.hss-drop').length).toBe(1);
      expect(row2.previousElementSibling?.matches('.hss-drop')).toBe(true);
      at(grip, 'pointerup', row2.getBoundingClientRect().top + 2);
      await settle();
      const group = server.calls.find((c) => c.method === 'POST' && c.path === '/cplugs/huddle/items/1/group');
      expect(group).toBeTruthy();
      expect(JSON.parse(group!.body)).toMatchObject({ group: 7, index: 0 });
      expect(server.calls.some((c) => c.path.endsWith('/order'))).toBe(false);
      expect(ghost()).toBeNull();
    });

    test(`${where}: below the last of that area's rows lands after it; Escape there writes nothing`, async () => {
      const { host, grip } = await grab('status', popout, 1);
      const row3 = host.querySelector('[data-huddle-item="3"]')!.getBoundingClientRect();
      at(grip, 'pointermove', row3.bottom - 2);
      expect(host.querySelector('[data-huddle-item="3"]')!.nextElementSibling?.matches('.hss-drop')).toBe(true);
      escape();
      at(grip, 'pointerup', row3.bottom - 2);
      await settle();
      expect(writes()).toEqual([]);
    });
  }
});
