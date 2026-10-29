/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const posts: string[] = [];
const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', ...extra,
});
/** Two open items and two closed (done) ones. */
const ITEMS = (list: string) => [mk(1, list), mk(2, list), mk(3, list, { state: 'done' }), mk(4, list, { state: 'done' })];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string }) => {
      if (init?.method === 'POST') posts.push(path);
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
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

/** Mount the session cell under the menu host. Output: the host element after the body settled. */
async function draw(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target: host, props: { cell: Mark2, hostId: 'mk2-body', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return host;
}

describe('TM Mark II foot and add row', () => {
  test('no hide completed eye and no remove completed key in the footer', async () => {
    const host = await draw();
    expect(host.querySelector('[data-task-manager-controls]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-hide-completed], [data-task-manager-remove-completed]')).toBeNull();
  });

  test('the send key is in the add row in the place of the add button, and the footer has none', async () => {
    const host = await draw();
    const row = host.querySelector('.hd-add') as HTMLElement;
    expect(row.querySelector('[data-task-manager-send]')).not.toBeNull();
    expect(row.querySelector('button[type="submit"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-controls] [data-task-manager-send]')).toBeNull();
  });

  test('with text typed the send key adds it as a new task', async () => {
    const host = await draw();
    const field = host.querySelector('[data-task-manager-add]') as HTMLInputElement;
    const send = host.querySelector('.hd-add [data-task-manager-send]') as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    field.value = 'a brand new task';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    flushSync();
    expect(send.disabled).toBe(false);
    send.click();
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    expect(posts.some((path) => path.endsWith('/inbox'))).toBe(true);
  });
});

describe('TM Mark II delete closed', () => {
  test('is a row of the widget menu that names the closed tasks in a warning and deletes only on confirm', async () => {
    await draw();
    const row = () => declaredActionsFor('mk2-body').find((a) => a.id === 'delete-closed')!;
    expect(row().label).toBe('delete closed');
    expect(row().blocked).toBeUndefined();
    row().run();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    const ask = document.querySelector('[data-mk2-delete-closed-ask]');
    expect(ask?.textContent).toContain('2 closed tasks');
    expect(ask?.textContent).toContain('for good');
    (document.querySelector('[data-mk2-delete-closed-cancel]') as HTMLElement).click();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    expect(posts.filter((path) => path.endsWith('/remove-completed'))).toEqual([]);
    row().run();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    (document.querySelector('[data-mk2-delete-closed-confirm]') as HTMLElement).click();
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    expect(posts.filter((path) => path.endsWith('/remove-completed'))).toEqual(['/cplugs/huddle/lists/7/remove-completed']);
  });
});

describe('TM Mark II chip row follows its width', () => {
  function barIs(px: number): void {
    vi.stubGlobal('ResizeObserver', class { cb: () => void; constructor(cb: () => void) { this.cb = cb; } observe(): void { this.cb(); } disconnect(): void {} });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return (this as HTMLElement).hasAttribute('data-task-manager-mk2-bar') ? px : 0; } });
  }

  test.each([[400, 'full'], [260, 'count'], [120, 'icon']])('at %ipx the row is %s', async (px, mode) => {
    barIs(px);
    const host = await draw();
    const bar = host.querySelector('[data-task-manager-mk2-bar]') as HTMLElement;
    expect(bar.getAttribute('data-mk2-chip-mode')).toBe(mode);
    for (const chip of host.querySelectorAll('[data-task-manager-mk2-chip]')) {
      expect(chip.getAttribute('aria-label')).toBeTruthy();
      expect(chip.querySelector('svg')).not.toBeNull();
    }
  });
});
