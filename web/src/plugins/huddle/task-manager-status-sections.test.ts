/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, section: string, position: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: string }[],
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  items: [] as unknown[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle' && method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { settings: Record<string, unknown> };
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return server.prefs;
      }
      if (path === '/cplugs/huddle') return server.prefs;
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 5, open: 5, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'widgets', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import { areaSubsections, clampInto, sectionOf, sectionReorder, statusSections, subsectionAt } from './task-manager-status-sections';
import { FOLDS_KEY, statusFolds } from './task-manager-status-folds.svelte';
import { STATUS_ICON } from './huddle-status';
import type { HuddleItem } from './huddle-model';
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

function drawn(host: HTMLElement): [string, string[]][] {
  return [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-section]')].map((s) => [
    s.dataset.taskManagerStatusSection as string, [...s.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((r) => r.dataset.huddleItem as string)]);
}

const LIST = () => [
  mk(1, 'open', 0), mk(2, 'review', 1, { group: 7, number: 3 }), mk(3, 'question', 2, { number: 1 }),
  mk(4, 'review', 3, { number: 4 }), mk(5, 'done', 4, { state: 'done', status: 'done' }),
];

beforeEach(async () => {
  server.calls = [];
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.items = LIST();
  statusFolds.choices = {};
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

const as = (raw: unknown[]): HuddleItem[] => raw as HuddleItem[];

describe('the section model', () => {
  test('the server section wins; an older server falls back to status, the ticked pair as done', () => {
    expect(sectionOf(as([mk(1, 'working', 0)])[0]!)).toBe('working');
    expect(sectionOf({ ...as([mk(1, 'x', 0)])[0]!, section: undefined, status: 'done' })).toBe('done');
    expect(sectionOf({ ...as([mk(1, 'x', 0)])[0]!, section: undefined, status: 'review' })).toBe('review');
  });

  test('sections run in the fixed order, each in priority order, and an empty one is left out', () => {
    expect(statusSections(as(LIST())).map((s) => [s.key, s.items.map((i) => i.id)]))
      .toEqual([['question', [3]], ['review', [2, 4]], ['open', [1]], ['done', [5]]]);
    expect(statusSections(as(LIST()), true).map((s) => s.key)).toEqual(['question', 'review', 'open']);
  });

  test('a drag inside a section moves only that section inside its own slots of the list', () => {
    const items = as(LIST());
    const review = statusSections(items).find((s) => s.key === 'review')!;
    expect(sectionReorder(items, review, 1, 0)).toEqual([1, 4, 3, 2, 5]);
    expect(sectionReorder(items, review, 0, 0)).toEqual([1, 2, 3, 4, 5]);
  });
});

describe('the status view on screen', () => {
  test('it is the default: the switch reads by status, sections in order, empty ones hidden, done folded', async () => {
    const host = await mountBody();
    expect(taskManagerPrefs.view).toBe('status');
    expect(host.querySelector('[data-task-manager-view]')!.getAttribute('data-task-manager-view')).toBe('status');
    expect(host.querySelector('[data-task-manager-view-key="status"]')!.getAttribute('aria-pressed')).toBe('true');
    expect(drawn(host)).toEqual([['question', ['3']], ['review', ['2', '4']], ['open', ['1']], ['done', []]]);
    expect(host.querySelector('[data-task-manager-status-head="working"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-status-fold="done"]')!.getAttribute('aria-expanded')).toBe('false');
    expect(host.querySelector('[data-task-manager-status-count="review"]')!.textContent).toBe('2');
    expect([...host.querySelectorAll('[data-task-manager-status-head] .hss-name')].map((n) => n.textContent))
      .toEqual(['question for you', 'ready to review', 'open', 'done']);
  });

  test('a status section header wears the same icon its rows wear', async () => {
    const host = await mountBody();
    const icon = (sel: string) => host.querySelector<HTMLElement>(`${sel} [data-task-manager-section-icon]`)!.dataset.taskManagerSectionIcon;
    expect(icon('[data-task-manager-status-head="question"]')).toBe(STATUS_ICON.question);
    expect(icon('[data-task-manager-status-head="review"]')).toBe(STATUS_ICON.review);
    expect(icon('[data-task-manager-status-head="open"]')).toBe(STATUS_ICON.open);
    expect(icon('[data-task-manager-status-head="done"]')).toBe(STATUS_ICON.done);
    expect(host.querySelector('[data-huddle-item="3"] [data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('question');
    expect(host.querySelector('[data-task-manager-status-head="question"] svg')).not.toBeNull();
  });

  test('a grouped row wears no area tag, its area heading already names it', async () => {
    const host = await mountBody(true);
    expect(host.querySelector('[data-huddle-item="2"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-area]')).toBeNull();
    expect(host.querySelector('.hdr-area')).toBeNull();
  });

  test('a reply moves an item out of ready to review on its own when the server says so', async () => {
    const host = await mountBody();
    server.items = LIST().map((i) => (i.id === 2 ? { ...i, status: 'waiting_to_send', section: 'waiting_to_send' } : i));
    await refreshTaskManager();
    await settle();
    expect(drawn(host).slice(0, 3)).toEqual([['question', ['3']], ['review', ['4']], ['open', ['2', '1']]]);
  });

  test('unfolding done shows its rows and is remembered on this device', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-status-fold="done"]')!.click();
    await settle();
    expect(drawn(host).at(-1)).toEqual(['done', ['5']]);
    expect(JSON.parse(localStorage.getItem(FOLDS_KEY) as string)).toEqual({ 'all/done': false });
  });

  test('the switch stores view and re-reads the list; by area draws the groups', async () => {
    const host = await mountBody();
    server.calls = [];
    host.querySelector<HTMLElement>('[data-task-manager-view-key="area"]')!.click();
    await settle();
    await new Promise((r) => setTimeout(r, 260));
    await settle();
    const put = server.calls.find((c) => c.method === 'PUT' && c.path === '/cplugs/huddle');
    expect(JSON.parse(put!.body)).toEqual({ revision: 3, settings: { view: 'area' } });
    expect(server.calls.some((c) => c.method === 'GET' && c.path === '/cplugs/huddle/lists/all?live_only=1')).toBe(true);
    expect(host.querySelector('[data-task-manager-status-section]')).toBeNull();
    expect(host.querySelector('[data-task-manager-section="7"]')).not.toBeNull();
  });

  test('the grip moves a row inside its section and sends the whole priority order', async () => {
    server.items = LIST().map((i) => (i.id === 4 ? { ...i, group: 7 } : i));
    await refreshTaskManager();
    const host = await mountBody();
    server.calls = [];
    host.querySelector<HTMLElement>('[data-task-manager-grip="2"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    await settle();
    const put = server.calls.find((c) => c.method === 'PUT' && c.path === '/cplugs/huddle/lists/all/order');
    expect(JSON.parse(put!.body)).toEqual({ ids: [1, 4, 3, 2, 5], expected_revision: 9 });
    server.calls = [];
    host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    await settle();
    expect(server.calls.some((c) => c.path.endsWith('/order'))).toBe(false);
  });
});

describe('by area, each area breaks into status subsections (docs/task-manager.md section 21, item 41)', () => {
  const AREA = () => [
    ...LIST(), mk(6, 'question', 5, { group: 7 }), mk(7, 'review', 6), mk(8, 'done', 7, { group: 7, state: 'done', status: 'done' }),
  ];

  test('pure: subsections in the status order, done folded, drawn rows skip a folded one, a drop stays inside its subsection', () => {
    const { subs, drawn: rows } = areaSubsections(as(AREA()).filter((i) => i.group == null), false, (k) => k === 'done');
    expect(subs.map((x) => [x.key, x.items.map((i) => i.id), x.start, x.folded]))
      .toEqual([['question', [3], 0, false], ['review', [4, 7], 1, false], ['open', [1], 3, false], ['done', [5], 4, true]]);
    expect(rows.map((i) => i.id)).toEqual([3, 4, 7, 1]);
    expect(subsectionAt(subs, 2)!.key).toBe('review');
    expect(subsectionAt(subs, 4)).toBeNull();
    expect(clampInto(subs[1]!, 0)).toBe(1);
    expect(clampInto(subs[1]!, 9)).toBe(2);
  });

  test('on screen: each area wears "<area>: <status>" sub-headers in the status colours; done folded; the grip stays in its subsection', async () => {
    server.prefs = { revision: 3, settings: { view: 'area' } };
    server.items = AREA();
    await refreshPrefs();
    await refreshTaskManager();
    const host = await mountBody(true);
    const heads = (key: string) => [...host.querySelectorAll<HTMLElement>(`[data-task-manager-section="${key}"] [data-task-manager-area-sub] .hds-sub-name`)].map((n) => n.textContent);
    expect(heads('none')).toEqual(['question for you', 'ready to review', 'open', 'done']);
    expect(heads('7')).toEqual(['widgets: question for you', 'widgets: ready to review', 'widgets: done']);
    const rows = (key: string) => [...host.querySelectorAll<HTMLElement>(`[data-task-manager-section="${key}"] [data-huddle-item]`)].map((r) => r.dataset.huddleItem);
    expect(rows('none')).toEqual(['3', '4', '7', '1']);
    expect(rows('7')).toEqual(['6', '2']);
    expect(host.querySelector('[data-task-manager-area-sub-fold="7:done"]')!.getAttribute('aria-expanded')).toBe('false');
    expect(host.querySelector<HTMLElement>('[data-task-manager-area-sub="7:question"] .hds-sub-mark')!.style.getPropertyValue('--_mark')).toBe('var(--oc-yellow-bright)');
    const subIcon = (key: string) => host.querySelector<HTMLElement>(`[data-task-manager-area-sub="${key}"] [data-task-manager-section-icon]`)!.dataset.taskManagerSectionIcon;
    expect(subIcon('7:question')).toBe(STATUS_ICON.question);
    expect(subIcon('7:review')).toBe(STATUS_ICON.review);
    expect(subIcon('7:done')).toBe(STATUS_ICON.done);
    expect(subIcon('none:open')).toBe(STATUS_ICON.open);
    expect(host.querySelector('[data-task-manager-group-count="7"]')!.textContent).toBe('3');
    host.querySelector<HTMLElement>('[data-task-manager-area-sub-fold="7:done"]')!.click();
    await settle();
    expect(rows('7')).toEqual(['6', '2', '8']);
    expect(rows('none')).toEqual(['3', '4', '7', '1']);
    server.calls = [];
    host.querySelector<HTMLElement>('[data-task-manager-grip="7"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    await settle();
    const put = server.calls.find((c) => c.method === 'PUT' && c.path === '/cplugs/huddle/lists/all/order');
    expect(JSON.parse(put!.body).ids).toEqual([1, 2, 3, 7, 5, 6, 4, 8]);
    server.calls = [];
    host.querySelector<HTMLElement>('[data-task-manager-grip="2"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    await settle();
    expect(server.calls.some((c) => c.path.endsWith('/order'))).toBe(false);
  });
});
