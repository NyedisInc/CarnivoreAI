/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
let reply: unknown = null;
let failure: Error | null = null;

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) { super(message); this.status = status; }
  },
  authFetch: async (path: string) => {
    calls.push(path);
    if (failure) throw failure;
    return reply;
  },
}));

import Cell from './Cell.svelte';
import { META } from '../../engine/meta';
import { columns } from './meta';
import { scheduledTasks } from '../../api/scheduled-tasks.svelte';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  calls.length = 0;
  reply = null;
  failure = null;
});

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

function render(width = 600): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(Cell, { target, props: { width, height: 300, meta: META['scheduled-tasks'], instance: 'scheduled-tasks', page: 'home' } as never }));
  flushSync();
  return target;
}

const TASKS = {
  state: 'ok', total: 2, truncated: false, runs_truncated: false, detail: '', as_of: null,
  tasks: [
    { id: 'nightly', name: 'nightly', description: 'check the fleet', file_state: 'ok', schedule: null,
      schedule_source: 'not_recorded', next_run_at: null, last_run_at: new Date(Date.now() - 3 * 3600000).toISOString(),
      runs_recorded: 4, updated_at: null },
    { id: 'weekly', name: 'weekly', description: null, file_state: 'ok', schedule: '0 9 * * 1',
      schedule_source: 'frontmatter', next_run_at: null, last_run_at: null, runs_recorded: 0, updated_at: null },
  ],
};

test('it lists what is recorded and nothing it would have to guess', async () => {
  reply = TASKS;
  const root = render();
  await settle();
  expect(calls).toEqual(['/scheduled-tasks']);
  const text = root.textContent ?? '';
  expect(text).toContain('nightly');
  expect(text).toContain('check the fleet');
  expect(text).toContain('not recorded');
  expect(text).toContain('0 9 * * 1');
  expect(text).toContain('3h ago');
  expect(text).toContain('no run recorded');
  expect(text).toContain('no description');
});

test('a task of a paired Mac shows its host and the same id on two Macs is two rows', async () => {
  const task = (host: string | null) => ({ ...TASKS.tasks[0], host_key: host, host_label: host ? 'hosta' : null });
  reply = { ...TASKS, total: 2, tasks: [task(null), task('peer-ab')] };
  const root = render();
  await settle();
  const names = [...root.querySelectorAll('.oc-st-name-text')].map((n) => n.textContent);
  expect(names).toEqual(['nightly', 'nightly @ hosta']);
});

test('a missing folder and an unreadable one are sentences, not an empty table', async () => {
  for (const [state, words] of [
    ['absent', 'no scheduled tasks folder on this machine'],
    ['unreadable', 'the scheduled tasks folder could not be read'],
  ] as const) {
    reply = { ...TASKS, state, tasks: [], total: 0 };
    const root = render();
    await settle();
    expect(root.querySelector('[data-scheduled-tasks-notice]')!.textContent!.trim()).toBe(words);
    for (const app of apps.splice(0)) unmount(app);
  }
});

test('it polls only while mounted', async () => {
  reply = TASKS;
  render();
  await settle();
  expect(scheduledTasks()).not.toBeNull();
  for (const app of apps.splice(0)) unmount(app);
  flushSync();
  expect(scheduledTasks()).toBeNull();
});

test('the name outranks the last run: it gets the larger floor and the larger share (a task item sizing)', () => {
  const name = columns.find((column) => column.key === 'name')!;
  const lastRun = columns.find((column) => column.key === 'lastRun')!;
  expect(name.minPx).toBeGreaterThan(lastRun.minPx);
  expect(name.weight).toBeGreaterThan(lastRun.weight * 2);
  expect(name.minPx + lastRun.minPx).toBeLessThanOrEqual(META['scheduled-tasks'].widthStates![0]!.min);
});
