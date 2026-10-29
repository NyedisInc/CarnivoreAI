/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: '7', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], github_issue: '', unread: false, ...extra,
});
const msg = (id: number, extra: Record<string, unknown>) => ({
  id: id * 10, item_id: id, author: 'claude', text: `message ${id}`, answered: false, unread: false, created_at: 1, seq: id, context: '', questions: [], ...extra,
});
const ITEMS = [
  mk(1, { status: 'working', section: 'working', needs_you: true, needs_action: 'read', unread: true, thread: [msg(1, { kind: 'answer', unread: true })] }),
  mk(2, { status: 'question', section: 'question', needs_you: true, needs_action: 'answer', thread: [msg(2, { kind: 'question', questions: ['pick'], form: [{ id: 'a', type: 'single', prompt: 'pick', required: true, options: [{ id: 'x', label: 'x' }], other: false }] })] }),
  mk(3, { status: 'working', section: 'working', unread: true, thread: [msg(3, { kind: 'answer', unread: true })] }),
  mk(4, { status: 'open', section: 'open' }),
  mk(5, { status: 'working', section: 'working', unread: true, thread: [msg(5, { kind: 'info', unread: true, id: 51 }), msg(5, { kind: 'info', unread: true, id: 52 }), msg(5, { kind: 'answer', unread: true, id: 53 })] }),
  mk(6, { status: 'question', section: 'question', needs_you: true, needs_action: 'answer', unread: true, thread: [msg(6, { id: 60, author: 'joe', kind: 'reply', unread: false }), msg(6, { id: 61, kind: 'answer', unread: true }), msg(6, { id: 62, kind: 'info', category: 'status', unread: false }), msg(6, { id: 63, kind: 'question', answered: true, unread: false })] }),
];

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'status', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 6, open: 1, review: 0, questions: 1, claude_seq: 0, unread: 3 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: structuredClone(ITEMS) }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: structuredClone(ITEMS) };
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
import Mk2HeadHost from './fixtures/Mk2HeadHost.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { toggleRow } from '../../../cplugs/huddle/huddle.svelte';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

async function settle(): Promise<void> { for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); } flushSync(); }
async function draw(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const props = { width: 380, height: 600, meta: metaFor('task-manager-mk2'), instance: 'tm', scope: { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 } };
  apps.push(mount(Mk2HeadHost, { target: host, props: { cell: Mark2, meta: metaFor('task-manager-mk2'), props } }));
  await settle();
  return host;
}
const strip = (host: HTMLElement, key: 'unread' | 'needs-you'): HTMLElement | null => host.querySelector(`[data-mk2-head-count="${key}"]`);
const numbers = (host: HTMLElement): { unread: string | undefined; needs: string | undefined } => ({
  unread: strip(host, 'unread')?.querySelector('.mk2-head-num')?.textContent ?? undefined,
  needs: strip(host, 'needs-you')?.querySelector('.mk2-head-num')?.textContent ?? undefined,
});

describe('the title strip carries needs you and unread, per task', () => {
  test('both counts, each the chip number, in words and in the narrow icon form', async () => {
    const host = await draw();
    expect(strip(host, 'needs-you')?.querySelector('.mk2-head-words')?.textContent).toBe('3 needs you');
    expect(strip(host, 'unread')?.querySelector('.mk2-head-words')?.textContent).toBe('7 unread');
    for (const key of ['needs-you', 'unread'] as const) {
      const one = strip(host, key)!;
      expect(one.querySelector('.mk2-head-ico svg')).not.toBeNull();
      expect(one.getAttribute('aria-label')).toBe(one.querySelector('.mk2-head-words')!.textContent);
      expect(one.getAttribute('title')).toBe(one.getAttribute('aria-label'));
    }
    expect(numbers(host)).toEqual({ unread: '7', needs: '3' });
  });

  test('a container query on the strip (not a viewport breakpoint) swaps words for icon and number', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/opscenter/cells/task-manager-mk2/mk2-design.css'), 'utf8');
    expect(css).toMatch(/@container oc-head \(max-width: \d+px\) \{[^}]*\.mk2-head-n \.mk2-head-words \{ display: none; \}[^}]*\.mk2-head-ico \{ display: inline-flex; \}[^}]*\.mk2-head-num \{ display: inline; \}/);
    expect(css).toMatch(/\.mk2-head-n \.mk2-head-ico, \.mk2-head-n \.mk2-head-num \{ display: none; \}/);
  });

  test('a held mark read drops both counts at once, the undo puts both back', async () => {
    const host = await draw();
    toggleRow(1);
    await settle();
    const key = host.querySelector<HTMLElement>('[data-task-manager-mark-read="1"]');
    expect(key).not.toBeNull();
    key!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '6', needs: '2' });
    host.querySelector<HTMLElement>('[data-task-manager-mark-read="1"]')!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '7', needs: '3' });
  });

  test('marking read a task with three unread messages drops the unread count by three, at once, and the undo puts all three back', async () => {
    const host = await draw();
    expect(numbers(host).unread).toBe('7');
    toggleRow(5);
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-mark-read="5"]')!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '4', needs: '3' });
    host.querySelector<HTMLElement>('[data-task-manager-mark-read="5"]')!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '7', needs: '3' });
  });

  test('the audit task: mark read drops the strip by exactly what its tab shows (2), and the undo puts both back', async () => {
    const host = await draw();
    toggleRow(6);
    await settle();
    expect(host.querySelector('[role="tab"]:nth-child(2)')?.textContent).toContain('2');
    host.querySelector<HTMLElement>('[data-task-manager-mark-read="6"]')!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '5', needs: '3' });
    host.querySelector<HTMLElement>('[data-task-manager-mark-read="6"]')!.click();
    await settle();
    expect(numbers(host)).toEqual({ unread: '7', needs: '3' });
  });
});
