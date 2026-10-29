/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const msg = (id: number, item: number, author: string, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: item, author, kind, text, answered: false, created_at: id, seq: id, ...extra });
const mk = (id: number, extra: Record<string, unknown>) => ({
  id, list: '7', text: `task ${id}`, title: `task ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], status: 'working', section: 'working', ...extra,
});
const flags = vi.hoisted(() => ({ scheduled: true }));
const ITEMS = () => [
  mk(21, { needs_you: true, needs_action: 'read', unread: true, info_unread: 1, info_unseen: true, thread: [msg(5, 21, 'claude', 'info', 'the build is green and ready', { unread: true })] }),
  mk(22, { thread: [1, 2, 3, 4, 5, 6].map((n) => msg(30 + n, 22, n % 2 ? 'claude' : 'joe', 'reply', `message number ${n}`, { unread: false })) }),
  ...(!flags.scheduled ? [] : [mk(23, { status: 'scheduled', section: 'scheduled', state: 'open', start_trigger: { kind: 'at', fire_at: 1893020620, fire_at_iso: '2030-01-26T09:17:00-04:00', repeat: { kind: 'daily', every: 1, time: '09:17' } } })]),
];

const wire = vi.hoisted(() => ({ writes: [] as string[], open: [] as Array<() => void> }));
vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: (path: string, init: RequestInit = {}) => {
      if (init.method && init.method !== 'GET') { wire.writes.push(path); return new Promise((resolve) => { wire.open.push(() => resolve({})); }); }
      if (path === '/swarm/roster') return Promise.resolve({ agents: [] });
      if (path === '/cplugs/huddle') return Promise.resolve({ revision: 1, settings: { view: 'status', hideCompleted: false } });
      if (path === '/cplugs/huddle/focus') return Promise.resolve({ focus: null });
      if (path === '/cplugs/huddle/lists') return Promise.resolve({ cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 1 }] });
      if (path.startsWith('/cplugs/huddle/aggregate')) return Promise.resolve({ cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: ITEMS() }] });
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return Promise.resolve({ list: one[1], revision: 1, cursor: 0, groups: [], items: ITEMS() });
      return Promise.resolve({});
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
import Mark2All from '../task-manager-mk2-all/Cell.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  flags.scheduled = true;
  wire.writes.length = 0;
  for (const release of wire.open.splice(0)) release();
  try { localStorage.clear(); } catch {  }
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function draw(state: 'compact' | 'opened' | 'detailed' = 'opened', all = false): Promise<HTMLElement> {
  localStorage.setItem('carnivore.core.task-manager-mk2.tm.task-state', JSON.stringify(state));
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(all
    ? mount(Mark2All, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager-mk2-all'), instance: 'tm', scope } })
    : mount(Mark2, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope } }));
  await settle();
  return host;
}

const sectionOfRow = (host: HTMLElement, id: number): string | null =>
  host.querySelector(`[data-huddle-item="${id}"]`)?.closest('[data-task-manager-status-section]')?.getAttribute('data-task-manager-status-section') ?? null;


describe('the schedule lives inline in the row', () => {
  test('an opened scheduled task draws no schedule block under the row; the time and edit are in the row line, pause and stop in its action tab', async () => {
    const host = await draw('opened');
    const row = host.querySelector('[data-huddle-item="23"]') as HTMLElement;
    expect(row.querySelector('[data-task-manager-schedule="23"]'), 'a schedule line still draws under the row').toBeNull();
    const line = row.querySelector('.hdr-line') as HTMLElement;
    expect(line.querySelector('[data-task-manager-due="23"]')).not.toBeNull();
    const edit = row.querySelector('[data-task-manager-schedule-edit-row="23"]') as HTMLElement;
    expect(line.contains(edit), 'edit is not on the row line').toBe(true);
    expect(edit.closest('.tkm-when')?.contains(line.querySelector('[data-task-manager-due="23"]')), 'time and edit are not one wrapping unit').toBe(true);
    expect(edit.getAttribute('data-btn')).not.toBeNull();
    const keys = row.querySelector('[data-mk2-tab="action"] [data-mk2-schedule-keys], [data-mk2-schedule-keys]') as HTMLElement;
    for (const key of ['schedule-pause', 'schedule-cancel']) {
      const el = keys.querySelector(`[data-task-manager-${key}="23"]`) as HTMLElement | null;
      expect(el, `${key} is not in the action tab`).not.toBeNull();
      expect(el!.getAttribute('data-btn')).not.toBeNull();
    }
  });

  test('stop clears the schedule', async () => {
    const host = await draw('opened');
    (host.querySelector('[data-task-manager-schedule-cancel="23"]') as HTMLElement).click();
    await settle();
    expect(wire.writes.includes('/cplugs/huddle/items/23')).toBe(true);
  });

  test('all projects with nothing scheduled draws no "scheduled / none scheduled" section at the bottom', async () => {
    flags.scheduled = false;
    const host = await draw('opened', true);
    expect(host.querySelector('[data-task-manager-schedule-strip]')).toBeNull();
    expect(host.querySelector('[data-task-manager-schedule-none]')).toBeNull();
    expect(host.querySelector('[data-task-manager-schedule-add]')).toBeNull();
  });
});
