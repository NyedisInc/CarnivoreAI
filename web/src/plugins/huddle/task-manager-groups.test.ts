/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { menuNode, openRowMenu } from './row-menu-driver.test.helper';

const server = vi.hoisted(() => ({ calls: [] as { path: string; method: string; body: string }[] }));

const mk = (id: number, group: number | null, number: number | null = id) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '',
  number, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group,
});
const GROUPS = [
  { id: 7, list: 'all', name: 'auth', position: 0, folded: false },
  { id: 8, list: 'all', name: 'sidebar', position: 1, folded: false },
  { id: 9, list: 'all', name: 'build', position: 2, folded: true },
];

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 5, open: 5, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'carnivore', project_id: 12, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 9, groups: [
          { list: 'all', name: null, project_id: null, revision: 3, groups: [], items: [mk(1, null, 1)] },
          { list: '12', name: 'carnivore', project_id: 12, revision: 9, groups: [{ id: 20, list: '12', name: 'ops', position: 0, folded: false }],
            items: [{ ...mk(11, null, 1), list: '12' }, { ...mk(12, 20, 2), list: '12' }] },
        ] };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: GROUPS,
          items: [mk(1, null, 1), mk(2, 7, 2), mk(3, 7, 3), mk(4, 8, 4), mk(5, 9, 5)] };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { dropTarget, regroup, sectionIndex, sectionsOf, type HuddleItem } from './huddle-model';
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
  server.calls = [];
  huddle.selected = 'all';
  huddle.openId = null;
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

const item = (id: number, group: number | null): HuddleItem => mk(id, group) as unknown as HuddleItem;

describe('the section model', () => {
  test('ungrouped first, then each group by its place; an unknown group reads as ungrouped; empty groups stay', () => {
    const groups = [{ id: 5, list: 'all', name: 'b', position: 1, folded: false }, { id: 4, list: 'all', name: 'a', position: 0, folded: false }];
    const out = sectionsOf([item(1, 5), item(2, null), item(3, 99)], groups);
    expect(out.map((s) => [s.group?.id ?? null, s.items.map((i) => i.id)])).toEqual([[null, [2, 3]], [4, []], [5, [1]]]);
  });

  test('regroup puts an item into a section at a place, mirroring the server', () => {
    const groups = [{ id: 5, list: 'all', name: 'g', position: 0, folded: false }];
    const out = regroup([item(1, null), item(2, null), item(3, 5)], groups, 1, 5, 0);
    expect(out.map((i) => [i.id, i.group])).toEqual([[2, null], [1, 5], [3, 5]]);
    expect(regroup(out, groups, 3, null, null).map((i) => i.id)).toEqual([2, 3, 1]);
  });

  test('a visible place maps past hidden rows, and the pointer picks the section under it', () => {
    expect(sectionIndex([1, 2, 3], [1, 3], 1)).toBe(2);
    expect(sectionIndex([1, 2, 3], [1, 3], 2)).toBe(3);
    expect(sectionIndex([], [], 0)).toBe(0);
    const boxes = [{ key: null, top: 0, bottom: 40, middles: [10, 30] }, { key: 5, top: 60, bottom: 100, middles: [70, 90] }];
    expect(dropTarget(boxes, 75, { key: null, index: 0 })).toEqual({ key: 5, index: 1 });
    expect(dropTarget(boxes, 50, { key: null, index: 0 })).toEqual({ key: 5, index: 0 });
    expect(dropTarget(boxes, 35, { key: null, index: 0 })).toEqual({ key: null, index: 1 });
  });
});

describe('the list draws its groups', () => {
  for (const popout of [false, true]) {
    test(`${popout ? 'pop-out' : 'sidebar'}: ungrouped first, then each group in status subsections; no numbers; a folded group hides its rows`, async () => {
      const host = await mountBody(popout);
      const sections = [...host.querySelectorAll<HTMLElement>('[data-task-manager-section]')];
      expect(sections.map((s) => [s.dataset.taskManagerSection, [...s.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((r) => r.dataset.huddleItem)]))
        .toEqual([['none', ['1']], ['7', ['2', '3']], ['8', ['4']], ['9', []]]);
      expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-section-head] .hds-name')].map((n) => n.textContent)).toEqual(['auth', 'sidebar', 'build']);
      expect(host.querySelector('[data-huddle-number]')).toBeNull();
      expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-area-sub] .hds-sub-name')].map((n) => n.textContent))
        .toEqual(['open', 'auth: open', 'sidebar: open']);
      expect(host.querySelector('[data-task-manager-fold="9"]')!.getAttribute('aria-expanded')).toBe('false');
      expect(host.querySelector('[data-task-manager-group-count="9"]')!.textContent).toBe('1');
    });
  }

  test('folding sends the flag and hides the rows at once', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-fold="7"]')!.click();
    flushSync();
    expect(host.querySelectorAll('[data-task-manager-section="7"] [data-huddle-item]').length).toBe(0);
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/groups/7' && c.method === 'PATCH' && JSON.parse(c.body).folded === true)).toBe(true);
  });

  test('a new group is made from the control row', async () => {
    const host = await mountBody(true);
    host.querySelector<HTMLElement>('[data-task-manager-new-group]')!.click();
    await settle();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-group-name]')!;
    input.value = 'docs';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    host.querySelector<HTMLElement>('[data-task-manager-group-create]')!.click();
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/lists/all/groups' && c.method === 'POST' && JSON.parse(c.body).name === 'docs')).toBe(true);
  });
});

describe('"all projects" shows groups under each project', () => {
  test('each list keeps its own sections under its heading', async () => {
    huddle.selected = 'aggregate';
    await refreshTaskManager();
    const host = await mountBody();
    const of = (list: string) => [...host.querySelectorAll<HTMLElement>(`[data-task-manager-group="${list}"] [data-task-manager-section]`)]
      .map((s) => [s.dataset.taskManagerSection, [...s.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((r) => r.dataset.huddleItem)]);
    expect(of('all')).toEqual([['none', ['1']]]);
    expect(of('12')).toEqual([['none', ['11']], ['20', ['12']]]);
    expect(host.querySelector('[data-task-manager-group="12"] [data-task-manager-section-head="20"] .hds-name')!.textContent).toBe('ops');
  });
});

describe('dragging a row into a group', () => {
  test('a drop over another section files the row there at the place under the pointer', async () => {
    const host = await mountBody();
    const tops = new Map<Element, { top: number; bottom: number }>();
    let y = 0;
    for (const el of host.querySelectorAll('[data-task-manager-section-head], [data-task-manager-section], [data-huddle-item]')) {
      if (el.hasAttribute('data-task-manager-section')) {
        const rows = el.querySelectorAll('[data-huddle-item]').length;
        tops.set(el, { top: y, bottom: y + Math.max(rows, 0) * 20 });
        continue;
      }
      tops.set(el, { top: y, bottom: y + 20 });
      y += 20;
    }
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const box = tops.get(this) ?? { top: 0, bottom: 0 };
      return { top: box.top, bottom: box.bottom, height: box.bottom - box.top, left: 0, right: 100, width: 100, x: 0, y: box.top, toJSON: () => ({}) } as DOMRect;
    });
    const grip = host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')!;
    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientY: 10, bubbles: true }));
    grip.dispatchEvent(new MouseEvent('pointermove', { clientY: 55, bubbles: true }));
    flushSync();
    expect(host.querySelector('[data-task-manager-section="7"] .hd-drop')).not.toBeNull();
    grip.dispatchEvent(new MouseEvent('pointerup', { clientY: 55, bubbles: true }));
    flushSync();
    expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-section="7"] [data-huddle-item]')].map((r) => r.dataset.huddleItem)).toEqual(['2', '1', '3']);
    await settle();
    const sent = server.calls.find((c) => c.path === '/cplugs/huddle/items/1/group');
    expect(sent && JSON.parse(sent.body)).toEqual({ group: 7, index: 1, expected_revision: 1 });
  });
});

describe('"move to" offers groups', () => {
  test('the open item lists its own list groups; choosing one files it there', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    openRowMenu(host, 2);
    await settle();
    menuNode('move-to')!.click();
    flushSync();
    menuNode('move-list:all')!.click();
    flushSync();
    expect(menuNode('move-group:all:7')!.getAttribute('aria-checked')).toBe('true');
    expect(menuNode('move-to:all')).not.toBeNull();
    menuNode('move-group:all:8')!.click();
    await settle();
    const sent = server.calls.find((c) => c.path === '/cplugs/huddle/items/2/group');
    expect(sent && JSON.parse(sent.body)).toEqual({ group: 8, expected_revision: 1 });
  });
});
