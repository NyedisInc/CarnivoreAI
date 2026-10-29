/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const ROW_PX = 40;
const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', ...extra,
});
const ITEMS = (list: string) => Array.from({ length: 12 }, (_, i) => mk(i + 1, list, { section: 'open', status: 'open' }));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 12, open: 12, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
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
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { HOLD_LEAVE_MS } from '../../../cplugs/huddle/task-manager-view-hold.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';

cplugEnablement.enabled = { huddle: true };

const apps: Array<ReturnType<typeof mount>> = [];
const resizeCallbacks: Array<() => void> = [];
const realRect = Element.prototype.getBoundingClientRect;

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resizeCallbacks.length = 0;
  Element.prototype.getBoundingClientRect = realRect;
  vi.unstubAllGlobals();
});

function modelLayout(): void {
  Element.prototype.getBoundingClientRect = function rect(this: Element): DOMRect {
    const box = this.closest('[data-task-manager-scroll]') as HTMLElement | null;
    const make = (top: number, height: number): DOMRect => ({ top, bottom: top + height, left: 0, right: 100, width: 100, height, x: 0, y: top, toJSON: () => ({}) });
    if (this.matches('[data-task-manager-scroll]')) return make(0, 300);
    if (this.matches('[data-huddle-item]') && box) {
      let y = 0;
      for (const row of box.querySelectorAll<HTMLElement>('[data-huddle-item]')) {
        const height = ROW_PX + Number(row.getAttribute('data-grow') ?? 0);
        if (row === this) return make(y - box.scrollTop, height);
        y += height;
      }
    }
    return make(0, 0);
  };
}

async function draw(): Promise<HTMLElement> {
  vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { resizeCallbacks.push(cb); } observe(): void {} unobserve(): void {} disconnect(): void {} });
  modelLayout();
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target: host, props: { cell: Mark2, hostId: 'mk2-body', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  return host;
}

async function settle(): Promise<void> { for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); } flushSync(); }
const scroller = (host: HTMLElement): HTMLElement => host.querySelector('[data-task-manager-scroll]') as HTMLElement;
function firstVisible(host: HTMLElement): { id: string; offset: number } {
  for (const row of host.querySelectorAll<HTMLElement>('[data-huddle-item]')) {
    const rect = row.getBoundingClientRect();
    if (rect.bottom > 0) return { id: row.getAttribute('data-huddle-item') ?? '', offset: rect.top };
  }
  return { id: '', offset: 0 };
}
function scrollTo(host: HTMLElement, to: number): void {
  scroller(host).scrollTop = to;
  scroller(host).dispatchEvent(new Event('scroll'));
}
async function letGo(host: HTMLElement): Promise<void> {
  scroller(host).dispatchEvent(new PointerEvent('pointerleave'));
  await new Promise((resolve) => setTimeout(resolve, HOLD_LEAVE_MS + 50));
  await settle();
}
function push(items: unknown[]): void {
  huddle.body = { ...(huddle.body as object), items } as typeof huddle.body;
  huddle.groups = (huddle.groups ?? []).map((g) => (g.list === '7' ? { ...g, items } : g)) as typeof huddle.groups;
}

describe('TM Mark II keeps the first visible row in place', () => {
  test('a task that leaves above the reading place does not move the row the owner reads', async () => {
    const host = await draw();
    scrollTo(host, 130);
    await letGo(host);
    const before = firstVisible(host);
    expect(before.id).not.toBe('');
    push(ITEMS('7').filter((i) => i.id !== 1 && i.id !== 2));
    await settle();
    expect(firstVisible(host)).toEqual(before);
    expect(scroller(host).scrollTop).toBe(130 - 2 * ROW_PX);
  });

  test('a new task inserted above does not move the row the owner reads', async () => {
    const host = await draw();
    scrollTo(host, 130);
    await letGo(host);
    const before = firstVisible(host);
    push([mk(99, '7', { section: 'open', status: 'open', position: 0 }), ...ITEMS('7')]);
    await settle();
    expect(firstVisible(host)).toEqual(before);
  });

  test('a row above that grows (a fold opening, text wrapping) does not move the row the owner reads', async () => {
    const host = await draw();
    scrollTo(host, 130);
    await letGo(host);
    const before = firstVisible(host);
    host.querySelector('[data-huddle-item="1"]')?.setAttribute('data-grow', '55');
    resizeCallbacks.forEach((cb) => cb());
    await settle();
    expect(firstVisible(host)).toEqual(before);
  });

  test('a push held while the owner looked lands without moving the row the owner reads', async () => {
    const host = await draw();
    scrollTo(host, 130);
    scroller(host).dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    await settle();
    const before = firstVisible(host);
    push(ITEMS('7').filter((i) => i.id !== 1 && i.id !== 2));
    await settle();
    scroller(host).dispatchEvent(new PointerEvent('pointerleave'));
    await new Promise((resolve) => setTimeout(resolve, HOLD_LEAVE_MS + 50));
    await settle();
    expect(firstVisible(host)).toEqual(before);
  });

  test('at the top of the list a new task shows there', async () => {
    const host = await draw();
    push([mk(99, '7', { section: 'open', status: 'open', position: 0 }), ...ITEMS('7')]);
    await settle();
    expect(scroller(host).scrollTop).toBe(0);
    expect(host.querySelector('[data-huddle-item]')?.getAttribute('data-huddle-item')).toBe('99');
  });

  test("the keeper's own correction is not the owner looking: it never arms the hold, so the next push lands at once", async () => {
    const host = await draw();
    scrollTo(host, 130);
    await letGo(host);
    push(ITEMS('7').filter((i) => i.id !== 1 && i.id !== 2));
    await settle();
    expect(scroller(host).scrollTop).toBe(130 - 2 * ROW_PX);
    scroller(host).dispatchEvent(new Event('scroll'));
    await settle();
    push(ITEMS('7').filter((i) => i.id !== 1 && i.id !== 2 && i.id !== 10));
    await settle();
    expect(host.querySelector('[data-huddle-item="10"]')).toBeNull();
  });
});
