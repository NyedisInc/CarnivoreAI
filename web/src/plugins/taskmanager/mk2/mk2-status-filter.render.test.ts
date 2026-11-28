/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../../opscenter/engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const ITEMS = (list: string) => [mk(1, list), mk(2, list, { needs_you: true, section: 'needs_you' }), mk(3, list), mk(4, list, { section: 'scheduled' })];

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: ITEMS('7') }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: ITEMS(one[1] as string) };
      return {};
    },
  };
});
vi.mock('../../../opscenter/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../opscenter/api')>()),
  sessions: { data: [{ session_row_id: 1, project_id: 7, session: { id: 'ses_1', working_dir: '/x' } }] },
}));
vi.mock('../../../opscenter/lib/active-terminal', () => ({
  activeTerminalSessionId: () => 'ses_1',
  activeTerminalSlot: () => 'terminal:@primary',
}));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Mark2 from './Cell.svelte';
import { hideableStatuses, isHiddenStatuses, withStatusShown } from './mk2-statuses';
import { stateKey } from '../../../opscenter/widgets/shell/widget-state.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import { declaredActionsFor } from '../../../opscenter/widgets/menu/declared-actions.svelte';
import { cplugEnablement } from '../../host/enablement.svelte';
import { clearViewFilter } from '../task-manager-view-filter.svelte';

cplugEnablement.enabled = { taskmanager: true };

const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  localStorage.clear();
});

async function draw(hostId: string, instance: string): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target, props: { cell: Mark2, hostId, props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance, scope } } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return target;
}

/** The item ids a host draws, sorted. Inputs: host. Output: string[]. */
const itemIds = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item') ?? '').sort();

const statusAction = (hostId: string, key: string) => declaredActionsFor(hostId).find((a) => a.id === `status:${key}`)!;

describe('TM Mark II status filter (#2970)', () => {
  test('the widget menu offers one checked "show <status>" checkbox per status type but done (show completed is its control)', async () => {
    await draw('tm-a', 'copy-a');
    const rows = declaredActionsFor('tm-a').filter((a) => a.id.startsWith('status:'));
    expect(rows.map((a) => a.id)).toEqual(['needs_you', 'question', 'review', 'waiting', 'working', 'scheduled', 'open', 'todo'].map((k) => `status:${k}`));
    expect(rows.every((a) => a.toggle === true && a.checked === true)).toBe(true);
    expect(rows.map((a) => a.label)).toEqual(['show needs you', 'show questions', 'show ready to review', 'show waiting', 'show working', 'show scheduled', 'show open', 'show todo']);
  });

  test('unticking a status hides its tasks in this copy only, and ticking it brings them back', async () => {
    const a = await draw('tm-a', 'copy-a');
    const b = await draw('tm-b', 'copy-b');
    expect(itemIds(a)).toEqual(['1', '2', '3', '4']);
    statusAction('tm-a', 'needs_you').run();
    flushSync();
    await tick();
    expect(statusAction('tm-a', 'needs_you').checked).toBe(false);
    expect(itemIds(a)).toEqual(['1', '3', '4']);
    expect(itemIds(b)).toEqual(['1', '2', '3', '4']);
    expect(statusAction('tm-b', 'needs_you').checked).toBe(true);
    statusAction('tm-a', 'needs_you').run();
    flushSync();
    await tick();
    expect(itemIds(a)).toEqual(['1', '2', '3', '4']);
  });

  test('the choice is the copy\'s own stored setting: a remount of the same copy still hides the status, a new copy does not', async () => {
    await draw('tm-a', 'copy-a');
    statusAction('tm-a', 'scheduled').run();
    flushSync();
    await tick();
    for (const app of apps.splice(0)) unmount(app);
    document.body.innerHTML = '';
    const again = await draw('tm-a2', 'copy-a');
    expect(itemIds(again)).toEqual(['1', '2', '3']);
    expect(statusAction('tm-a2', 'scheduled').checked).toBe(false);
    const fresh = await draw('tm-c', 'copy-c');
    expect(itemIds(fresh)).toEqual(['1', '2', '3', '4']);
  });
});

describe('TM Mark II chip counts follow the status filter (#2970)', () => {
  test('a task of an unticked status leaves the chip counts too', async () => {
    const host = await draw('tm-a', 'copy-a');
    const label = (chip: string): string => host.querySelector(`[data-task-manager-mk2-chip="${chip}"]`)?.getAttribute('aria-label') ?? '';
    expect(label('needs_you')).toBe('needs you (1)');
    statusAction('tm-a', 'needs_you').run();
    flushSync();
    await tick();
    expect(label('needs_you')).toBe('needs you');
  });
});

describe('a set saved with done by an earlier build (#2970)', () => {
  test('done is dropped on load, the other hidden statuses stay, and the next change writes it clean', async () => {
    expect(isHiddenStatuses(['done', 'scheduled'])).toBe(true);
    expect(hideableStatuses(['done', 'scheduled'])).toEqual(['scheduled']);
    expect(withStatusShown(['done', 'scheduled'], 'open', false)).toEqual(['scheduled', 'open']);
    localStorage.setItem(stateKey('core.task-manager-mk2', 'hidden-statuses', 'copy-old'), JSON.stringify(['done', 'scheduled']));
    const host = await draw('tm-old', 'copy-old');
    expect(itemIds(host)).toEqual(['1', '2', '3']);
    expect(declaredActionsFor('tm-old').some((a) => a.id === 'status:done')).toBe(false);
    statusAction('tm-old', 'scheduled').run();
    flushSync();
    await tick();
    expect(JSON.parse(localStorage.getItem(stateKey('core.task-manager-mk2', 'hidden-statuses', 'copy-old')) ?? 'null')).toEqual([]);
    expect(itemIds(host)).toEqual(['1', '2', '3', '4']);
  });
});

describe('a set saved with only done (#2970)', () => {
  test('nothing counts as hidden: the all chip reads pressed, since done has no box to bring it back', async () => {
    localStorage.setItem(stateKey('core.task-manager-mk2', 'hidden-statuses', 'copy-done'), JSON.stringify(['done']));
    const host = await draw('tm-done', 'copy-done');
    expect(host.querySelector('[data-task-manager-mk2-chip="all"]')?.getAttribute('aria-pressed')).toBe('true');
  });
});
