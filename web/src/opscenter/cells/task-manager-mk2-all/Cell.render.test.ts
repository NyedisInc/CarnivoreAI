/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount, type Component } from 'svelte';
import type { CellProps } from '../../lib/cell';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const row = (key: string, name: string, project_id: number, unread = 0) => ({ key, name, project_id, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread });

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [row('7', 'Carnivore', 7, 2), row('9', 'Billing', 9, 1)] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [one[1] === '7' ? mk(1, '7', { needs_you: true, section: 'needs_you' }) : mk(2, '9', { unread: true })] };
      if (path.split('?')[0] === '/cplugs/huddle/aggregate') {
        return { cursor: 0, groups: [
          { list: '7', name: 'Carnivore', items: [mk(1, '7', { needs_you: true, section: 'needs_you' })] },
          { list: '9', name: 'Billing', items: [mk(2, '9', { unread: true })] },
        ] };
      }
      return {};
    },
  };
});
vi.mock('../../lib/active-terminal', () => ({
  activeTerminalSessionId: () => 'ses_1',
  activeTerminalSlot: () => 'terminal:@primary',
}));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Original from '../task-manager-all/Cell.svelte';
import Mark2All, { TASK_MANAGER_MK2_ALL_WIDGET } from './Cell.svelte';
import Mk2Host from '../task-manager-mk2/fixtures/Mk2Host.svelte';
import Mk2HeadHost from '../task-manager-mk2/fixtures/Mk2HeadHost.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { swarmView } from '../../../cplugs/huddle/huddle-swarm-view.svelte';

cplugEnablement.enabled = { huddle: true };

const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
});

async function draw(cell: typeof Original | typeof Mark2All): Promise<HTMLElement> {
  swarmView.view = 'lists';
  const host = document.createElement('div');
  document.body.appendChild(host);
  apps.push(mount(cell as Component<CellProps>, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager-all'), instance: 'tm' } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return host;
}

function shown(host: HTMLElement) {
  return {
    marker: host.querySelector('[data-task-manager-all-cell]') !== null,
    heads: [...host.querySelectorAll('[data-task-manager-heading]')].map((el) => el.textContent?.trim() ?? ''),
    items: [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item')),
  };
}

describe('TM Mark II all beside the original all task managers cell', () => {
  test('draws every list under its project head, the same as the original', async () => {
    const original = shown(await draw(Original));
    const mark2 = shown(await draw(Mark2All));
    expect(mark2.heads).toEqual(['Carnivore', 'Billing']);
    expect(mark2.items).toEqual(['1', '2']);
    expect(mark2).toEqual(original);
  });

  test('takes no session scope: a session scope handed to it changes nothing', async () => {
    const plain = shown(await draw(Mark2All));
    const host = document.createElement('div');
    document.body.appendChild(host);
    const scope = { sessionId: 'ses_2', rowId: 2, workingDir: '/y', projectId: 9 };
    apps.push(mount(Mark2All, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager-mk2-all'), instance: 'tm', scope } }));
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    expect(shown(host)).toEqual(plain);
  });
});

const itemIds = (host: HTMLElement): string[] => [...host.querySelectorAll('[data-huddle-item]')].map((el) => el.getAttribute('data-huddle-item') ?? '').sort();

async function press(host: HTMLElement, chip: string): Promise<void> {
  (host.querySelector(`[data-task-manager-mk2-chip="${chip}"]`) as HTMLButtonElement).click();
  await tick();
  flushSync();
}

describe('TM Mark II all header', () => {
  test('the top row is the search alone and no project dropdown stands in the header', async () => {
    const host = await draw(Mark2All);
    const bar = host.querySelector('[data-task-manager-mk2-bar]') as HTMLElement;
    expect(bar).not.toBeNull();
    expect(host.querySelector('[data-task-manager-widget-bar]')).toBeNull();
    expect(host.querySelector('select[data-huddle-pick], #task-list-pick')).toBeNull();
    expect(bar.querySelector('select')).toBeNull();
    expect(host.querySelector('[data-task-manager-view-key], [data-huddle-density-key], [data-task-manager-status-filter]')).toBeNull();
    const top = bar.firstElementChild as HTMLElement;
    expect(top.querySelectorAll('input, button, select').length).toBe(1);
    expect(top.querySelector('input[type="search"]')).not.toBeNull();
  });

  test('the chips run all, needs you, unread, scheduled, and each filters across every project', async () => {
    const host = await draw(Mark2All);
    expect([...host.querySelectorAll('[data-task-manager-mk2-chip]')].map((el) => el.getAttribute('data-task-manager-mk2-chip')))
      .toEqual(['all', 'needs_you', 'unread', 'scheduled']);
    expect(itemIds(host)).toEqual(['1', '2']);
    await press(host, 'needs_you');
    expect(itemIds(host)).toEqual(['1']);
    await press(host, 'unread');
    expect(itemIds(host)).toEqual(['2']);
    await press(host, 'scheduled');
    expect(itemIds(host)).toEqual([]);
    await press(host, 'all');
    expect(itemIds(host)).toEqual(['1', '2']);
    expect(host.querySelector('[data-task-manager-mk2-chip="show_completed"]')).toBeNull();
  });

  test('the title strip prints the new Task Manager count of every list', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const props = { width: 380, height: 600, meta: metaFor('task-manager-mk2-all'), instance: 'tm' };
    apps.push(mount(Mk2HeadHost, { target: host, props: { cell: Mark2All, meta: metaFor('task-manager-mk2-all'), props } }));
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    expect(host.querySelector('[data-mk2-head-count="unread"] .mk2-head-words')?.textContent).toBe('1 unread');
    expect(host.querySelector('.oc-frame-count')).toBeNull();
  });

  test('the widget menu carries the same controls as the session view', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(Mk2Host, { target, props: { cell: Mark2All, hostId: 'mk2-all-menu', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2-all'), instance: 'tm' } } }));
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    const actions = declaredActionsFor('mk2-all-menu');
    expect(actions.map((a) => a.id)).toEqual(TASK_MANAGER_MK2_ALL_WIDGET.actions.map((a) => a.id));
    expect(actions.map((a) => a.id)).toEqual(['group-by-area', 'density-compact', 'density-cozy', 'density-detailed', 'accordion', 'show-completed', 'show-counts', 'project-colors', 'status-bar', 'delete-closed']);
  });
});
