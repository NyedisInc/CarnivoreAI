/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { resolve } from 'node:path';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const msg = (id: number, author: 'joe' | 'claude', text: string) => ({ id, item_id: 5, author, kind: 'reply', text, answered: false, created_at: 1_700_000_000 + id, seq: id });
/** Item 5 carries a thread (the last agent message is new), a note, a tag and a fork parent. */
const OPEN = (list: string) => mk(5, list, {
  title: 'ship the tabs', text: 'ship the tabs now', note: 'check phone width', unread: true, tagged_by: 'cv-ui', forked_from: 2,
  thread: [msg(1, 'claude', 'first reply, spec at https://example.com/spec'), msg(2, 'joe', 'my answer'), msg(3, 'claude', 'second reply')], thread_count: 3,
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 1 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: [mk(1, '7'), OPEN('7')] }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [mk(1, one[1] as string), OPEN(one[1] as string)] };
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
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

cplugEnablement.enabled = { huddle: true };
/** A file under `cells/`, from the web root vitest runs in. Inputs: relative path. Output: absolute path. */
const CELLS = (rel: string): string => resolve(process.cwd(), 'src/opscenter/cells', rel);
const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
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

/** Mount a cell on project 7, inside a frame header when `hostId` is given. Output: the host element after it settled. */
async function draw(cell: typeof Mark2, hostId?: string): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  const props = { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope };
  apps.push(hostId ? mount(Mk2Host, { target: host, props: { cell, hostId, props } }) : mount(cell, { target: host, props }));
  await settle();
  return host;
}

/** Open task 5 by its row's toggle. Inputs: host. Output: the detail element. */
async function open(host: HTMLElement): Promise<HTMLElement> {
  (host.querySelector('[data-task-manager-toggle="5"]') as HTMLButtonElement).click();
  await settle();
  return host.querySelector('[data-task-manager-detail="5"]') as HTMLElement;
}


/** Forget the in-memory side of the view, as a page reload does. */
function reload(): void {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
}

async function mountCopy(instance: string): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mark2, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance, scope } }));
  await settle();
  return host;
}

describe('TM Mark II remembers its view across a reload', () => {
  test('the search, the chip, the open task and its tab come back, and another copy keeps its own', async () => {
    const first = await mountCopy('mk2-a');
    const search = first.querySelector('input.mk2-field') as HTMLInputElement;
    search.value = 'ship';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    (first.querySelector('[data-task-manager-mk2-chip="unread"]') as HTMLButtonElement).click();
    await settle();
    (first.querySelector('[role="tab"][id$="-tab-details"]') as HTMLButtonElement).click();
    await settle();

    reload();
    const again = await mountCopy('mk2-a');
    expect((again.querySelector('input.mk2-field') as HTMLInputElement).value).toBe('ship');
    expect(again.querySelector('[data-task-manager-mk2-chip="unread"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(again.querySelector('[data-task-manager-detail="5"]')).not.toBeNull();
    expect(again.querySelector('[data-task-manager-mk2-tab]')?.getAttribute('data-task-manager-mk2-tab')).toBe('details');

    reload();
    const other = await mountCopy('mk2-b');
    expect((other.querySelector('input.mk2-field') as HTMLInputElement).value).toBe('');
    expect(other.querySelector('[data-task-manager-mk2-tab]')).toBeNull();
  });

  test('an untouched copy writes nothing, and a stored view that cannot be drawn reads as the default', async () => {
    await mountCopy('mk2-c');
    expect(localStorage.getItem('carnivore.core.task-manager-mk2.mk2-c.view')).toBeNull();
    reload();
    localStorage.setItem('carnivore.core.task-manager-mk2.mk2-d.view', JSON.stringify({ query: 7, chip: 'nope' }));
    const host = await mountCopy('mk2-d');
    expect((host.querySelector('input.mk2-field') as HTMLInputElement).value).toBe('');
  });
});
