/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const ROW_PX = 40;
const CARD_PX = 200;
const SLACK_PX = 3;
const OPEN = 6;

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: '7', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', unread: false, ...extra,
});
const msg = (id: number, extra: Record<string, unknown>) => ({
  id: id * 10, item_id: id, author: 'claude', text: `message ${id}`, answered: false, unread: false, created_at: 1, seq: id, context: '', questions: [], ...extra,
});
const asking = (id: number) => mk(id, {
  status: 'question', section: 'question', needs_you: true, needs_action: 'answer',
  thread: [msg(id, { kind: 'question', questions: ['pick one'], form: [{ id: 'a', type: 'single', prompt: 'pick one', required: true, options: [{ id: 'x', label: 'x' }], other: false }] })],
});
const toRead = (id: number) => mk(id, { status: 'working', section: 'working', needs_you: true, needs_action: 'read', unread: true, thread: [msg(id, { kind: 'answer', unread: true })] });

const server = { items: [] as ReturnType<typeof mk>[] };
function seed(open: 'read' | 'question'): void {
  server.items = [
    ...[1, 2, 3, 4, 5].map(asking),
    open === 'read' ? toRead(OPEN) : asking(OPEN),
    asking(7),
    ...Array.from({ length: 12 }, (_, i) => mk(i + 8, { status: 'open', section: 'open' })),
  ];
}

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: server.items.length, open: 12, review: 0, questions: 6, claude_seq: 0, unread: 1 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: structuredClone(server.items) }] };
      const ask = /^\/cplugs\/huddle\/questions\/(\d+)$/.exec(path);
      if (ask) return { item: Number(ask[1]) / 10, message: Number(ask[1]), typed: true, ask: { context: '', questions: [] }, answered: false, answer_message_id: null };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: structuredClone(server.items) };
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
import { huddle, toggleRow } from '../../../cplugs/huddle/huddle.svelte';
import { HOLD_LEAVE_MS } from '../../../cplugs/huddle/task-manager-view-hold.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { MARK_READ_HOLD_SECONDS } from './mk2-mark-read.svelte';

cplugEnablement.enabled = { huddle: true };

const apps: Array<ReturnType<typeof mount>> = [];
/** The ResizeObserver callbacks a test can fire by hand (jsdom has none). */
const resizeCallbacks: Array<() => void> = [];
const realRect = Element.prototype.getBoundingClientRect;

afterEach(() => {
  vi.useRealTimers();
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  huddle.openId = null;
  resizeCallbacks.length = 0;
  Element.prototype.getBoundingClientRect = realRect;
  vi.unstubAllGlobals();
});

/** Lay the rows out by the model: the list box at y 0, each row ROW_PX tall in document order (plus its data-grow), minus the scroll. */
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

/** Settle the store and the DOM. Output: Promise<void>. */
async function settle(): Promise<void> { for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); } flushSync(); }
const scroller = (host: HTMLElement): HTMLElement => host.querySelector('[data-task-manager-scroll]') as HTMLElement;
const rowOf = (host: HTMLElement, id: number): HTMLElement | null => host.querySelector(`[data-huddle-item="${id}"]`);
function firstVisible(host: HTMLElement): { id: string; offset: number } {
  for (const row of host.querySelectorAll<HTMLElement>('[data-huddle-item]')) {
    const rect = row.getBoundingClientRect();
    if (rect.bottom > 0) return { id: row.getAttribute('data-huddle-item') ?? '', offset: rect.top };
  }
  return { id: '', offset: 0 };
}

async function drawReading(open: 'read' | 'question'): Promise<HTMLElement> {
  seed(open);
  vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { resizeCallbacks.push(cb); } observe(): void {} unobserve(): void {} disconnect(): void {} });
  modelLayout();
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mk2Host, { target: host, props: { cell: Mark2, hostId: 'mk2-body', props: { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope } } }));
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
  toggleRow(OPEN);
  await settle();
  rowOf(host, OPEN)?.setAttribute('data-grow', String(CARD_PX));
  resizeCallbacks.forEach((cb) => cb());
  scroller(host).scrollTop = 4 * ROW_PX + 20;
  scroller(host).dispatchEvent(new Event('scroll'));
  scroller(host).dispatchEvent(new PointerEvent('pointerleave'));
  await new Promise((resolve) => setTimeout(resolve, HOLD_LEAVE_MS + 50));
  await settle();
  return host;
}

describe('TM Mark II stays put when he reads or dismisses a task mid-list (round 9)', () => {
  test('mark read: the task leaves "needs you" and the first row he sees stays where it was', async () => {
    const host = await drawReading('read');
    const before = firstVisible(host);
    expect(before).toEqual({ id: '5', offset: -20 });
    const key = host.querySelector<HTMLElement>(`[data-task-manager-mark-read="${OPEN}"]`);
    expect(key).not.toBeNull();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    key?.click();
    await vi.advanceTimersByTimeAsync(MARK_READ_HOLD_SECONDS * 1000 + 100);
    vi.useRealTimers();
    await settle();
    expect(rowOf(host, OPEN)?.closest('[data-task-manager-status-section]')?.getAttribute('data-task-manager-status-section')).toBe('working');
    const after = firstVisible(host);
    expect(after.id).toBe(before.id);
    expect(Math.abs(after.offset - before.offset)).toBeLessThanOrEqual(SLACK_PX);
  });

  test('dismiss: the dismissed question files the task out of "needs you" and the first row he sees stays where it was', async () => {
    const host = await drawReading('question');
    const before = firstVisible(host);
    expect(before).toEqual({ id: '5', offset: -20 });
    const key = rowOf(host, OPEN)?.querySelector<HTMLElement>('[data-task-manager-question-dismiss]');
    expect(key).toBeTruthy();
    key?.click();
    await settle();
    await settle();
    const after = firstVisible(host);
    expect(after.id).toBe(before.id);
    expect(Math.abs(after.offset - before.offset)).toBeLessThanOrEqual(SLACK_PX);
  });
});
