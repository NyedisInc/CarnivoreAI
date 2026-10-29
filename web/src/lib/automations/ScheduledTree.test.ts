/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { TaskManagerSchedule } from '../task-manager-schedules/task-manager-scheduled';
import { buildScheduledTree } from './scheduled-tree';

const state = vi.hoisted(() => ({ on: true, rows: [] as unknown[] }));
vi.mock('../task-manager-schedules/task-manager-addon.svelte', () => ({ taskManagerAddonOn: () => state.on }));
vi.mock('../task-manager-reveal/reveal', () => ({ openTaskManagerItem: vi.fn(async () => null) }));
vi.mock('./scheduled-store.svelte', () => ({
  scheduled: { get rows() { return state.rows; }, answered: true },
  followScheduled: () => () => undefined,
  loadScheduled: vi.fn(async () => undefined),
}));
vi.mock('./page-store.svelte', () => ({
  data: { projects: [{ id: 1, name: 'beta', folder: '/b' }, { id: 2, name: 'alpha', folder: '/a' }], sessionsWanted: true, notice: '' },
  sessionOptions: () => [{ session_uuid: 'u-1', label: 'argent', project_id: 2 }, { session_uuid: 'u-2', label: 'bare' }],
  wantSessions: vi.fn(async () => undefined),
}));

const item = (n: number, over: Partial<TaskManagerSchedule> = {}): TaskManagerSchedule => ({
  list: '7', item: n, title: `item ${n}`, fireAt: 1_900_000_000 + n, paused: false, state: 'pending', sessionKey: null, projectId: null,
  repeat: { freq: 'daily', time: '09:00' }, source: { id: n, revision: 1, text: 't', title: `item ${n}`, thread: [], start_trigger: { kind: 'at', fire_at: 1_900_000_000, fired_at: null, last_error: null, repeat: null } } as never,
  ...over,
});

test('items file by session, then project, then unassigned, and empty nodes are left out', () => {
  const projects = [{ id: 1, name: 'beta', folder: '/b' }, { id: 2, name: 'alpha', folder: '/a' }, { id: 3, name: 'empty', folder: '/e' }];
  const sessions = [{ session_uuid: 'u-1', label: 'argent', project_id: 2 }, { session_uuid: 'u-2', label: 'bare' }, { session_uuid: 'u-3', label: 'idle', project_id: 2 }];
  const tree = buildScheduledTree(projects, sessions, [
    item(1, { sessionKey: 'u-1' }),
    item(2, { projectId: 1 }),
    item(3, { sessionKey: 'u-2' }),
    item(4, { sessionKey: 'gone', projectId: 99 }),
  ]);
  expect(tree.map((n) => n.key)).toEqual(['project:2', 'project:1', 'unassigned']);
  expect(tree[0]!.children.map((c) => [c.label, c.schedules.map((s) => s.item)])).toEqual([['argent', [1]]]);
  expect(tree[1]!.schedules.map((s) => s.item)).toEqual([2]);
  expect(tree[2]!.schedules.map((s) => s.item)).toEqual([4]);
  expect(tree[2]!.children.map((c) => [c.label, c.schedules.map((s) => s.item)])).toEqual([['bare', [3]]]);
});

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function draw(): Promise<void> {
  const { default: ScheduledTree } = await import('./ScheduledTree.svelte');
  app = mount(ScheduledTree, { target: document.body });
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
}

test('the tree draws nodes and one row per item with icons, and nothing while the plugin is off', async () => {
  state.on = true;
  state.rows = [item(1, { sessionKey: 'u-1' }), item(2, { projectId: 1 })];
  await draw();
  expect([...document.querySelectorAll('[data-tree-node]')].map((n) => n.getAttribute('data-tree-node'))).toEqual(['project:2', 'session:u-1', 'project:1']);
  expect(document.querySelectorAll('[data-task-manager-schedule]').length).toBe(2);
  expect(document.querySelectorAll('[data-sched="edit"] svg').length).toBe(2);
  unmount(app!);
  app = null;
  document.body.innerHTML = '';
  state.on = false;
  await draw();
  expect(document.querySelector('[data-scheduled-tree]')).toBeNull();
});
