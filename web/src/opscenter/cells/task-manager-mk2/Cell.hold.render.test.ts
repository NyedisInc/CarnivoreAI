/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const posts: string[] = [];
const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', ...extra,
});
const ITEMS = (list: string) => [mk(1, list, { section: 'open', status: 'open' }), mk(2, list, { section: 'working', status: 'working' }), mk(3, list, { section: 'review', status: 'review' })];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string }) => {
      if (init?.method === 'POST') posts.push(path);
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 4, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
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

import Mark2 from './Cell.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { HOLD_LEAVE_MS } from '../../../cplugs/huddle/task-manager-view-hold.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';

cplugEnablement.enabled = { huddle: true };

const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  posts.length = 0;
  clearViewFilter();
  vi.unstubAllGlobals();
});

async function draw(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target: host, props: { cell: Mark2, hostId: 'mk2-body', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return host;
}

const order = (host: HTMLElement): number[] => [...host.querySelectorAll('[data-huddle-item]')].map((row) => Number(row.getAttribute('data-huddle-item')));
async function settle(): Promise<void> { for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); } flushSync(); }
function push(items: unknown[]): void {
  huddle.body = { ...(huddle.body as object), items } as typeof huddle.body;
  huddle.groups = (huddle.groups ?? []).map((g) => (g.list === '7' ? { ...g, items } : g)) as typeof huddle.groups;
}

describe('TM Mark II holds the layout while the owner looks', () => {
  test('a task that changes section, a new task and a removed task do not move the rows until the pointer leaves', async () => {
    const host = await draw();
    const before = order(host);
    expect(before.length).toBe(3);
    (host.querySelector('[data-task-manager-scroll]') as HTMLElement).dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    await settle();
    const live = ITEMS('7');
    push([{ ...live[0], section: 'question', status: 'question', needs_you: true }, live[2], mk(9, '7', { section: 'open', status: 'open', position: 0 })]);
    await settle();
    expect(order(host)).toEqual(before);
    (host.querySelector('[data-task-manager-scroll]') as HTMLElement).dispatchEvent(new PointerEvent('pointerleave'));
    await new Promise((resolve) => setTimeout(resolve, HOLD_LEAVE_MS + 50));
    await settle();
    expect(order(host)).not.toEqual(before);
    expect(order(host)).toContain(9);
    expect(order(host)).not.toContain(2);
  });

  test('without the pointer on the list a push lands at once', async () => {
    const host = await draw();
    const live = ITEMS('7');
    push([live[0], live[1]]);
    await settle();
    expect(order(host)).not.toContain(3);
  });
});
