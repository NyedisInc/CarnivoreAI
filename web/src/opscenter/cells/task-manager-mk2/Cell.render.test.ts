/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const ITEMS = (list: string) => [mk(1, list), mk(2, list, { needs_you: true, section: 'needs_you' }), mk(3, list, { unread: true }), mk(4, list, { section: 'scheduled' })];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 2 }] };
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
vi.mock('../../lib/active-terminal', () => ({
  activeTerminalSessionId: () => 'ses_1',
  activeTerminalSlot: () => 'terminal:@primary',
}));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Original from '../task-manager/Cell.svelte';
import Mark2, { TASK_MANAGER_MK2_WIDGET } from './Cell.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import Mk2HeadHost from './fixtures/Mk2HeadHost.svelte';
import { listTasksOf } from './mk2-head-count';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { taskManagerPrefs } from '../../../cplugs/huddle/task-manager-prefs.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';

cplugEnablement.enabled = { huddle: true };

const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
});

async function draw(cell: typeof Original, projectId: number | null): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId };
  apps.push(mount(cell, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return host;
}

function shown(host: HTMLElement) {
  return {
    list: host.querySelector('[data-task-manager-cell]')?.getAttribute('data-task-manager-cell'),
    items: [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item')),
    note: host.querySelector('[role="status"]')?.textContent?.trim() ?? '',
  };
}

describe('TM Mark II beside the original task manager cell', () => {
  test('a session in a project pins the same list and draws the same items', async () => {
    const original = shown(await draw(Original, 7));
    const mark2 = shown(await draw(Mark2, 7));
    expect(mark2.list).toBe('7');
    expect(mark2).toEqual(original);
  });

  test('a session with no project says the same sentence (the shell draws it, so no list is pinned)', async () => {
    const original = await draw(Original, null);
    const mark2 = await draw(Mark2, null);
    expect(mark2.querySelector('[data-huddle-item]')).toBeNull();
    expect(mark2.textContent?.trim()).toBe('this session has no project, so it has no task manager list');
    expect(mark2.textContent?.trim()).toBe(original.textContent?.trim());
  });
});

const itemIds = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item') ?? '').sort();

async function press(host: HTMLElement, chip: string): Promise<void> {
  (host.querySelector(`[data-task-manager-mk2-chip="${chip}"]`) as HTMLButtonElement).click();
  await tick();
  flushSync();
}

async function menuActions() {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target, props: { cell: Mark2, hostId: 'mk2-menu', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
  for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return declaredActionsFor('mk2-menu');
}

describe('TM Mark II header', () => {
  test('the top row is the search alone: no list picker, no view or density keys, no status funnel', async () => {
    const host = await draw(Mark2, 7);
    const bar = host.querySelector('[data-task-manager-mk2-bar]') as HTMLElement;
    expect(bar).not.toBeNull();
    expect(host.querySelector('[data-task-manager-widget-bar]')).toBeNull();
    expect(host.querySelector('select[data-huddle-pick], #task-list-pick')).toBeNull();
    expect(host.querySelector('[data-task-manager-view-key], [data-huddle-density-key], [data-task-manager-accordion-key], [data-task-manager-status-filter], [data-task-manager-search-key]')).toBeNull();
    const top = bar.firstElementChild as HTMLElement;
    expect([...top.querySelectorAll('input, button, select')].map((el) => el.getAttribute('data-task-manager-search') ?? el.tagName)).toEqual(['']);
    expect(top.querySelector('input[type="search"]')).not.toBeNull();
  });

  test('the chips run all, needs you, unread, scheduled, in lowercase, and show completed is no chip', async () => {
    const host = await draw(Mark2, 7);
    const chips = [...host.querySelectorAll('[data-task-manager-mk2-chip]')];
    expect(chips.map((el) => el.getAttribute('data-task-manager-mk2-chip'))).toEqual(['all', 'needs_you', 'unread', 'scheduled']);
    expect(chips.map((el) => el.textContent?.replace(/\d+/g, '').trim())).toEqual(['all', 'needs you', 'unread', 'scheduled']);
    expect(chips.every((el) => el.textContent === el.textContent?.toLowerCase())).toBe(true);
  });

  test('each chip filters the rows, and all brings every row back', async () => {
    const host = await draw(Mark2, 7);
    expect(itemIds(host)).toEqual(['1', '2', '3', '4']);
    const all = host.querySelector('[data-task-manager-mk2-chip="all"]') as HTMLElement;
    expect(all.getAttribute('aria-pressed')).toBe('true');
    await press(host, 'needs_you');
    expect(itemIds(host)).toEqual(['2']);
    expect(all.getAttribute('aria-pressed')).toBe('false');
    await press(host, 'unread');
    expect(itemIds(host)).toEqual(['3']);
    await press(host, 'scheduled');
    expect(itemIds(host)).toEqual(['4']);
    await press(host, 'scheduled');
    expect(itemIds(host)).toEqual(['1', '2', '3', '4']);
    await press(host, 'unread');
    await press(host, 'all');
    expect(itemIds(host)).toEqual(['1', '2', '3', '4']);
    expect(all.getAttribute('aria-pressed')).toBe('true');
  });

  test('search filters on its own and all clears it', async () => {
    const host = await draw(Mark2, 7);
    const field = host.querySelector('[data-task-manager-search]') as HTMLInputElement;
    field.value = 'item 3';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    flushSync();
    expect(itemIds(host)).toEqual(['3']);
    await press(host, 'all');
    expect(itemIds(host)).toEqual(['1', '2', '3', '4']);
    expect((host.querySelector('[data-task-manager-search]') as HTMLInputElement).value).toBe('');
  });

  test('show completed is a checkbox of the widget menu: the hide completed setting seen the other way round', async () => {
    const actions = await menuActions();
    const action = () => declaredActionsFor('mk2-menu').find((a) => a.id === 'show-completed')!;
    expect(actions.find((a) => a.id === 'show-completed')?.label).toBe('show completed');
    expect(taskManagerPrefs.hideCompleted).toBe(false);
    expect(action().toggle).toBe(true);
    expect(action().checked).toBe(true);
    action().run();
    flushSync();
    expect(taskManagerPrefs.hideCompleted).toBe(true);
    expect(action().checked).toBe(false);
  });

  test('the title strip prints the new Task Manager count of the session project, nothing before the list is read', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const props = { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope: { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 } };
    apps.push(mount(Mk2HeadHost, { target: host, props: { cell: Mark2, meta: metaFor('task-manager-mk2'), props } }));
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    expect(host.querySelector('[data-mk2-head-count="unread"] .mk2-head-words')?.textContent).toBe('1 unread');
    expect(host.querySelector('.oc-frame-count')).toBeNull();
    expect(listTasksOf(null, '7')).toBeNull();
    expect(listTasksOf(huddle.body, '9')).toBeNull();
  });

  test('the widget menu carries the view, density, accordion and status counts the header lost', async () => {
    const actions = await menuActions();
    expect(actions.map((a) => a.id)).toEqual(TASK_MANAGER_MK2_WIDGET.actions.map((a) => a.id));
    expect(actions.map((a) => a.id)).toEqual(['group-by-area', 'density-compact', 'density-cozy', 'density-detailed', 'accordion', 'show-completed', 'show-counts', 'project-colors', 'status-bar', 'delete-closed']);
    expect(actions.map((a) => a.label)).toEqual(['by group', 'compact', 'opened', 'detailed', 'accordion', 'show completed', 'status counts', 'project colors', 'status bar', 'delete closed']);
    const byId = (id: string) => declaredActionsFor('mk2-menu').find((a) => a.id === id)!;
    expect(byId('density-compact').checked).toBe(true);
    byId('density-detailed').run();
    flushSync();
    expect(byId('density-detailed').checked).toBe(true);
    expect(byId('density-compact').checked).toBe(false);
    expect(taskManagerPrefs.density).not.toBe('detailed');
    byId('accordion').run();
    flushSync();
    expect(taskManagerPrefs.accordion).toBe(true);
    expect(byId('accordion').checked).toBe(true);
  });
});
