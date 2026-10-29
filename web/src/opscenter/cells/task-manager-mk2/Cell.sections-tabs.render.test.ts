/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown>) => ({
  id, list, text: `task ${id}`, title: `task ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const SECTIONS: Array<[string, number, Record<string, unknown>]> = [
  ['needs_you', 11, { needs_you: true, needs_action: 'decide' }],
  ['review', 12, { state: 'review', status: 'review', review_description: 'look', review_where: 'here', review_action: 'tick' }],
  ['open', 13, { status: 'open' }],
  ['working', 14, { status: 'working' }],
  ['waiting', 15, { status: 'waiting' }],
  ['todo', 16, { status: 'todo' }],
  ['done', 17, { state: 'done', status: 'done' }],
];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 7, open: 7, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: SECTIONS.map(([, id, extra]) => mk(id, '7', extra)) }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: SECTIONS.map(([, id, extra]) => mk(id, one[1] as string, extra)) };
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
import { cplugEnablement } from '../../../cplugs/huddle/../host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
import { setViewChip } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { effectiveState, MK2_DEFAULT_STATE } from './mk2-task-state';
import type { TaskState } from '../../../lib/base/task-wrapper';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  try { localStorage.clear(); } catch { /* jsdom without storage */ }
});

/** Settle the mocked reads. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function draw(cell: typeof Mark2 = Mark2, instance = 'tm', state?: TaskState): Promise<HTMLElement> {
  if (state) localStorage.setItem(`carnivore.core.task-manager-mk2.${instance}.task-state`, JSON.stringify(state));
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(cell, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance, scope } }));
  await settle();
  for (const key of ['todo', 'done']) {
    const fold = host.querySelector(`[data-task-manager-status-fold="${key}"]`) as HTMLButtonElement | null;
    if (fold?.getAttribute('aria-expanded') === 'false') { fold.click(); await settle(); }
  }
  return host;
}

const tabsOf = (host: HTMLElement, id: number): HTMLElement | null => host.querySelector(`[data-task-manager-mk2-tabs="${id}"]`);

async function press(host: HTMLElement, id: number): Promise<void> {
  (host.querySelector(`[data-task-manager-toggle="${id}"]`) as HTMLButtonElement).click();
  await settle();
}

describe('every section draws a task that can open to the tabs', () => {
  test.each(SECTIONS)('a %s task (id %i) opens to the four tabs', async (section, id) => {
    const host = await draw();
    const row = host.querySelector(`[data-huddle-item="${id}"]`) as HTMLElement;
    expect(row, `no row for the ${section} task`).not.toBeNull();
    expect(row.closest(`[data-task-manager-status-section="${section}"]`), `the ${section} task is in the wrong section`).not.toBeNull();
    await press(host, id);
    expect(tabsOf(host, id), 'a press on the compact row peeks the task').not.toBeNull();
    expect([...tabsOf(host, id)!.querySelectorAll('[role="tab"]')].length).toBe(4);
  });

  test('in an opened view every task of every section shows its tabs together (no one-at-a-time accordion)', async () => {
    const host = await draw(Mark2, 'tm', 'opened');
    expect(SECTIONS.map(([section, id]) => [section, tabsOf(host, id) !== null])).toEqual(SECTIONS.map(([section]) => [section, true]));
  });
});

async function inState(state: TaskState): Promise<HTMLElement> {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  return draw(Mark2, `tm-${state}`, state);
}

const wrapperOf = (host: HTMLElement, id: number): HTMLElement | null => host.querySelector(`[data-huddle-item="${id}"] > .oc-task`);

const partsDrawn = (host: HTMLElement, id: number): string[] => [...(wrapperOf(host, id)?.querySelectorAll(':scope > [data-task-part]') ?? [])].map((el) => (el as HTMLElement).dataset.taskPart as string);

describe('every task is one wrapper (round 4 point 7)', () => {
  test('every task in every section draws through the one wrapper, with the same row parts', async () => {
    const host = await draw();
    for (const [section, id] of SECTIONS) {
      const wrapper = wrapperOf(host, id);
      expect(wrapper, `the ${section} task is not in the wrapper`).not.toBeNull();
      expect(wrapper!.querySelector(':scope > .oc-task__row > .oc-task__toggle[data-task-manager-toggle]'), `the ${section} task has no row toggle`).not.toBeNull();
      expect(wrapper!.querySelector('.oc-task__row [data-task-manager-grip], .oc-task__row .tkm-grip-gap'), `the ${section} task has no lead`).not.toBeNull();
      expect(wrapper!.querySelector('.oc-task__row [data-task-manager-status-icon]'), `the ${section} task has no status icon`).not.toBeNull();
      expect(wrapper!.querySelector('.oc-task__row [data-task-manager-row-title]'), `the ${section} task has no title`).not.toBeNull();
    }
  });

  test('COMPACT: exactly one line, the row alone: no tabs and no reply box, for every section', async () => {
    const host = await inState('compact');
    for (const [section, id] of SECTIONS) {
      expect(wrapperOf(host, id)!.dataset.taskState).toBe('compact');
      expect(partsDrawn(host, id), section).toEqual([]);
      expect(tabsOf(host, id)).toBeNull();
      expect(wrapperOf(host, id)!.querySelector(`[data-huddle-reply="${id}"]`), `${section} draws a reply box in compact`).toBeNull();
    }
  });

  test('OPENED: the row and the tab strip, always, with the reply box at the bottom of the tab panel, for every section', async () => {
    const host = await inState('opened');
    for (const [section, id] of SECTIONS) {
      expect(wrapperOf(host, id)!.dataset.taskState).toBe('opened');
      expect(partsDrawn(host, id), section).toEqual(['tabs']);
      expect(tabsOf(host, id), section).not.toBeNull();
      const panel = tabsOf(host, id)!.querySelector('.tn-tabbody') as HTMLElement;
      expect(panel.querySelector(`.mk2-reply [data-huddle-reply="${id}"]`), `${section} has no reply box in the panel`).not.toBeNull();
      expect(panel.lastElementChild?.classList.contains('mk2-reply'), `${section}: the reply box is not last in the panel`).toBe(true);
      expect(tabsOf(host, id)!.querySelector('[data-mk2-detailed]'), `${section} is detailed while opened`).toBeNull();
    }
  });

  test('DETAILED: the same strip and the reply box, with every panel at full length', async () => {
    const host = await inState('detailed');
    for (const [section, id] of SECTIONS) {
      expect(wrapperOf(host, id)!.dataset.taskState).toBe('detailed');
      expect(partsDrawn(host, id), section).toEqual(['tabs']);
      const panel = tabsOf(host, id)!.querySelector('.tn-tabbody') as HTMLElement;
      expect(panel.hasAttribute('data-mk2-detailed'), section).toBe(true);
      expect(panel.querySelector(`.mk2-reply [data-huddle-reply="${id}"]`), `${section} has no reply box in the panel`).not.toBeNull();
    }
  });

  test('a review task keeps its review block inside the wrapper, in the action tab, opened or detailed', async () => {
    for (const state of ['opened', 'detailed'] as TaskState[]) {
      const host = await inState(state);
      expect(wrapperOf(host, 12)!.querySelector('[data-task-part="tabs"] [data-task-manager-mk2-tab="action"] .tkm-review'), state).not.toBeNull();
    }
  });

  test('every task row shows the same parts in every state: status icon, title and meta, and no state word in the head', async () => {
    for (const state of ['compact', 'opened', 'detailed'] as TaskState[]) {
      const host = await inState(state);
      for (const [section, id] of SECTIONS) {
        const row = wrapperOf(host, id)!.querySelector('.oc-task__row') as HTMLElement;
        const title = row.querySelector(`[data-task-manager-row-title="${id}"]`);
        expect(title?.textContent?.trim(), `${section} (${id}) has no title when ${state}`).toBeTruthy();
        expect(row.querySelector('[data-task-manager-status-icon]'), `${section} (${id}) has no status icon when ${state}`).not.toBeNull();
        expect(row.querySelector('.tkm-tag'), `${section} (${id}) shows a stray state word when ${state}`).toBeNull();
      }
    }
  });

  test('a part with nothing inside draws no band: every visible part under a row holds an element', async () => {
    const host = await inState('opened');
    for (const [section, id] of SECTIONS) {
      for (const part of wrapperOf(host, id)!.querySelectorAll(':scope > [data-task-part]') as NodeListOf<HTMLElement>) {
        if (!part.hidden) expect(part.childElementCount, `${section} (${id}) draws an empty ${part.dataset.taskPart}`).toBeGreaterThan(0);
      }
    }
  });

  test('NEVER A MIXED VIEW: in each of the three states every task of every section is in that one state', async () => {
    for (const state of ['compact', 'opened', 'detailed'] as TaskState[]) {
      const host = await inState(state);
      expect(new Set(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)), state).toEqual(new Set([state]));
    }
  });

  test('a press on a compact row peeks that ONE task and a press anywhere else closes it; the other tasks stay compact', async () => {
    const host = await draw();
    await press(host, 13);
    expect(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)).toEqual(SECTIONS.map(([, id]) => (id === 13 ? 'opened' : 'compact')));
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    await settle();
    expect(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)).toEqual(SECTIONS.map(() => 'compact'));
  });

  test('in an opened view a press on a row changes nothing: no task has a state of its own', async () => {
    const host = await inState('opened');
    await press(host, 13);
    expect(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)).toEqual(SECTIONS.map(() => 'opened'));
  });

  test('point B: the unread and needs you chips draw every matching task opened, with its tabs; no chip leaves the view compact', async () => {
    expect(effectiveState('compact', 'unread')).toBe('opened');
    expect(effectiveState('compact', 'needs_you')).toBe('opened');
    expect(effectiveState('compact', 'scheduled')).toBe('compact');
    expect(effectiveState('compact', null)).toBe('compact');
    expect(effectiveState('detailed', 'unread')).toBe('detailed');
    const host = await draw();
    setViewChip('needs_you', (item) => item.needs_you === true);
    await settle();
    const rows = [...host.querySelectorAll('[data-huddle-item]')];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.map((row) => row.querySelector('.oc-task')?.getAttribute('data-task-state'))).toEqual(rows.map(() => 'opened'));
    expect(rows.every((row) => row.querySelector('[data-task-manager-mk2-tabs]') !== null)).toBe(true);
  });

  test('an untouched task is compact, one line with no tabs, whatever the menu density', async () => {
    const host = await draw();
    expect(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)).toEqual(SECTIONS.map(() => 'compact'));
    expect(SECTIONS.map(([, id]) => tabsOf(host, id) !== null)).toEqual(SECTIONS.map(() => false));
    expect(MK2_DEFAULT_STATE).toBe('compact');
  });

  test('the original task manager does not change: no wrapper, still one open row at a time', async () => {
    const host = await draw(Original, 'orig');
    expect(host.querySelector('.oc-task')).toBeNull();
    expect(host.querySelector('[data-task-state]')).toBeNull();
    for (const id of [11, 12]) { (host.querySelector(`[data-task-manager-toggle="${id}"]`) as HTMLButtonElement).click(); await settle(); }
    expect(host.querySelectorAll('[data-task-manager-detail]').length).toBe(1);
  });
});

describe('the one state survives a reload', () => {
  const KEY = 'carnivore.core.task-manager-mk2.mk2-states.task-state';

  test('the view state is kept per copy and comes back with no press; an untouched copy stores nothing', async () => {
    const untouched = await draw(Mark2, 'mk2-untouched');
    expect(untouched.querySelector('.oc-task')).not.toBeNull();
    expect(localStorage.getItem('carnivore.core.task-manager-mk2.mk2-untouched.task-state')).toBeNull();
    for (const app of apps.splice(0)) unmount(app);
    document.body.innerHTML = '';

    localStorage.setItem(KEY, JSON.stringify('detailed'));
    const again = await draw(Mark2, 'mk2-states');
    expect(SECTIONS.map(([, id]) => wrapperOf(again, id)!.dataset.taskState)).toEqual(SECTIONS.map(() => 'detailed'));
  });

  test('a stored value that cannot be drawn reads as the default, compact', async () => {
    localStorage.setItem(KEY, JSON.stringify('wide'));
    const host = await draw(Mark2, 'mk2-states');
    expect(SECTIONS.map(([, id]) => wrapperOf(host, id)!.dataset.taskState)).toEqual(SECTIONS.map(() => 'compact'));
  });
});
