/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const CHECKS = [
  { id: 'c1', label: 'tests pass', checked: true, checked_at: 1_700_000_000, checked_by: 'joe' },
  { id: 'c2', label: 'looks right on a phone', checked: false, checked_at: null, checked_by: null },
];
const saved = CHECKS.map((c) => ({ ...c }));
const ITEMS = (list: string) => [
  mk(5, list, { title: 'ship the tabs', review_checks: saved }),
  mk(6, list, { title: 'write the test', forked_from: 5, forked_from_title: 'ship the tabs', tagged_by: 'cv-ui' }),
  mk(7, list, { title: 'wire the route', forked_from: 5, forked_from_title: 'ship the tabs', state: 'review' }),
  mk(8, list, { title: 'unrelated', forked_from: 2 }),
];
const writes: Array<{ path: string; init: { method?: string; body?: string } | undefined }> = [];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'PATCH') {
        writes.push({ path, init });
        const hit = saved.find((c) => path.endsWith(`/${c.id}`));
        if (hit) Object.assign(hit, { checked: JSON.parse(init.body ?? '{}').checked });
        return {};
      }
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: ITEMS('7') }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: ITEMS(one[1] as string) };
      return {};
    },
  };
});
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  sessions: { data: [{ session_row_id: 1, project_id: 7, session: { id: 'ses_1', working_dir: '/x' } }] },
}));
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Original from '../task-manager/Cell.svelte';
import Mark2 from './Cell.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { subtasksOf } from './mk2-subtasks';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  writes.length = 0;
  saved.splice(0, saved.length, ...CHECKS.map((c) => ({ ...c })));
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  try { localStorage.clear(); } catch { /* jsdom without storage: the widget keeps an in-memory value */ }
});

/** Settle the mocked reads. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function openTask(cell: typeof Original, id = 5): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  apps.push(mount(cell, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope: { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 } } }));
  await settle();
  (host.querySelector(`[data-task-manager-toggle="${id}"]`) as HTMLButtonElement).click();
  await settle();
  return host.querySelector(`[data-task-manager-detail="${id}"]`) as HTMLElement;
}
const openFive = (cell: typeof Original): Promise<HTMLElement> => openTask(cell, 5);

async function pick(detail: HTMLElement, id: string): Promise<HTMLElement> {
  (detail.querySelector(`[role="tab"][id$="-tab-${id}"]`) as HTMLButtonElement).click();
  await settle();
  return detail.querySelector('[data-task-manager-mk2-tab]') as HTMLElement;
}

describe('TM Mark II subtasks tab', () => {
  test('a fourth tab, subtasks, sits after details', async () => {
    const detail = await openFive(Mark2);
    expect([...detail.querySelectorAll('[role="tab"]')].map((el) => el.textContent?.replace(/\s*·\s*\d+ new/, '').trim())).toEqual(['action', 'discussion', 'details', 'subtasks']);
  });

  test('each fork of the task is a row with its title, status and owner, and only this task forks', async () => {
    const body = await pick(await openFive(Mark2), 'subtasks');
    expect(body.dataset.taskManagerMk2Tab).toBe('subtasks');
    const rows = [...body.querySelectorAll('[data-mk2-subtask]')];
    expect(rows.map((r) => (r as HTMLElement).dataset.mk2Subtask)).toEqual(['6', '7']);
    expect(rows.map((r) => [r.querySelector('.mk2-sub-title')?.textContent, r.querySelector('[data-mk2-subtask-status]')?.textContent, r.querySelector('[data-mk2-subtask-owner]')?.textContent]))
      .toEqual([['write the test', 'open', 'cv-ui'], ['wire the route', 'in review', 'joe']]);
  });

  test('pressing a subtask opens that task', async () => {
    const body = await pick(await openFive(Mark2), 'subtasks');
    (body.querySelector('[data-mk2-subtask="7"]') as HTMLButtonElement).click();
    await settle();
    expect(huddle.openId).toBe(7);
  });

  test('a task with no forks says so, and shows the line naming the task it was forked from', async () => {
    const eight = await openTask(Mark2, 8);
    const body = await pick(eight, 'subtasks');
    expect(body.querySelector('[data-mk2-subtasks-none]')?.textContent).toBe('no subtasks');
    expect(body.querySelector('[data-task-manager-forked="8"]')).not.toBeNull();
  });

  test('the forked-from line leaves the open row in Mark II and stays in the original task manager', async () => {
    const mk2 = await openTask(Mark2, 8);
    expect(mk2.querySelector(':scope > [data-task-manager-forked]')).toBeNull();
    for (const app of apps.splice(0)) unmount(app);
    document.body.innerHTML = '';
    huddle.openId = null as never;
    const original = await openTask(Original, 8);
    expect(original.querySelector(':scope > [data-task-manager-forked="8"]')).not.toBeNull();
  });

  test('subtasksOf lists only live forks of the parent, with the owner the tag or the author', () => {
    const items = [...ITEMS('7'), mk(9, '7', { forked_from: 5, deleted: true })] as unknown as HuddleItem[];
    expect(subtasksOf(5, items).map((r) => [r.id, r.owner])).toEqual([[6, 'cv-ui'], [7, 'joe']]);
    expect(subtasksOf(99, items)).toEqual([]);
  });
});

describe('TM Mark II review checklist', () => {
  test('the action tab draws every review check as a base checkbox row with its saved tick, who and when', async () => {
    const body = await pick(await openFive(Mark2), 'action');
    const boxes = [...body.querySelectorAll('[data-mk2-checks] .oc-option')] as HTMLElement[];
    expect(boxes.map((b) => [b.getAttribute('role'), b.getAttribute('aria-checked'), b.querySelector('.oc-option__label')?.textContent])).toEqual([
      ['checkbox', 'true', 'tests pass'], ['checkbox', 'false', 'looks right on a phone'],
    ]);
    expect(boxes[0]?.querySelector('.oc-option__reason')?.textContent).toMatch(/^ticked by joe \S/);
    expect(boxes[1]?.querySelector('.oc-option__reason')).toBeNull();
  });

  test('ticking sends the one existing route and shows at once; unticking sends false', async () => {
    const body = await pick(await openFive(Mark2), 'action');
    const rows = () => [...body.querySelectorAll('[data-mk2-checks] .oc-option')] as HTMLButtonElement[];
    rows()[1]?.click();
    await settle();
    expect(writes.map((w) => [w.path, w.init?.method, JSON.parse(w.init?.body ?? '{}')])).toEqual([['/cplugs/huddle/items/5/review-checks/c2', 'PATCH', { checked: true }]]);
    expect(rows()[1]?.getAttribute('aria-checked')).toBe('true');
    rows()[0]?.click();
    await settle();
    expect(JSON.parse(writes[1]?.init?.body ?? '{}')).toEqual({ checked: false });
  });
});
