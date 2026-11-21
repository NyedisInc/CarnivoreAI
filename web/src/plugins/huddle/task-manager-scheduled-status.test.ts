/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, section: string, position: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position, created_by: 'joe', state: 'open', kind: '',
  number: null, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  view: 'status', items: [] as unknown[], patches: [] as { path: string; body: Record<string, unknown> }[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH') server.patches.push({ path, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: server.view } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 2 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: [{ id: 7, list: 'all', name: 'widgets', position: 0, folded: false }], items: server.items };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { SECTION_ICON, SECTION_ORDER, sectionOf, statusSections } from './task-manager-status-sections';
import { FOLDS_KEY, statusFolds } from './task-manager-status-folds.svelte';
import { STATUS_ICON, statusOf } from './huddle-status';
import type { HuddleItem } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

const SOON = () => Date.now() / 1000 + 3 * 3600;
const trigger = (fire_at: number, extra: Record<string, unknown> = {}) => ({ kind: 'at', fire_at, fire_at_iso: '', fired_at: null, last_error: null, ...extra });

const LIST = () => [
  mk(1, 'open', 0), mk(2, 'scheduled', 1, { start_trigger: trigger(SOON()) }),
  mk(3, 'open', 2, { start_trigger: trigger(SOON(), { fired_at: 1 }) }),
  mk(4, 'scheduled', 3, { group: 7, start_trigger: trigger(SOON()) }),
];

beforeEach(() => {
  statusFolds.choices = {};
  server.patches = [];
  huddle.selected = 'all';
  huddle.openId = null;
  server.items = LIST();
  try { globalThis.localStorage?.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable in the test env */ }
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(view: string, popout: boolean): Promise<HTMLElement> {
  server.view = view;
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

describe('the model', () => {
  test('scheduled sits below working and above open, has a clock icon of its own, and is not folded', () => {
    const order: readonly string[] = SECTION_ORDER;
    expect(order.indexOf('scheduled')).toBe(order.indexOf('working') + 1);
    expect(order.indexOf('open')).toBe(order.indexOf('scheduled') + 1);
    expect(STATUS_ICON.scheduled).toBe('status-scheduled');
    expect(SECTION_ICON.scheduled).toBe('status-scheduled');
    expect(STATUS_ICON.scheduled).not.toBe(STATUS_ICON.todo);
    const item = mk(2, 'scheduled', 1) as unknown as HuddleItem;
    expect(statusOf(item)).toBe('scheduled');
    expect(sectionOf(item)).toBe('scheduled');
    expect(statusSections(LIST() as unknown as HuddleItem[]).map((s) => s.key)).toEqual(['scheduled', 'open']);
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('status view: a scheduled section above open, its rows wear the clock and the time, a fired one sits in open', async () => {
    const host = await mountBody('status', popout);
    const heads = [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-head]')].map((h) => h.dataset.taskManagerStatusHead);
    expect(heads).toEqual(['scheduled', 'open']);
    const head = host.querySelector<HTMLElement>('[data-task-manager-status-head="scheduled"]')!;
    expect(head.dataset.folded).not.toBe('on');
    expect(head.querySelector('[data-task-manager-section-icon]')).not.toBeNull();
    const rows = [...host.querySelectorAll<HTMLElement>('[data-task-manager-status-section="scheduled"] [data-huddle-item]')];
    expect(rows.map((r) => r.dataset.huddleItem).sort()).toEqual(['2', '4']);
    expect(rows[0]!.querySelector('[data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('scheduled');
    const due = host.querySelector<HTMLElement>('[data-task-manager-due="2"]')!;
    expect(due.dataset.dueState).toBe('pending');
    expect(due.textContent).toMatch(/(today|tomorrow) \d{1,2}:\d\d (am|pm)/);
    const fired = host.querySelector<HTMLElement>('[data-task-manager-status-section="open"] [data-huddle-item="3"]')!;
    expect(fired.querySelector('[data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('open');
    expect(fired.querySelector<HTMLElement>('[data-task-manager-due="3"]')!.dataset.dueState).toBe('fired');
  });

  test('area view: the row wears the scheduled icon inside its area', async () => {
    const host = await mountBody('area', popout);
    expect(host.querySelector('[data-task-manager-area-sub="7:scheduled"]'), 'the area keeps a scheduled subsection').not.toBeNull();
    const row = host.querySelector<HTMLElement>('[data-huddle-item="4"]')!;
    expect(row.querySelector('[data-task-manager-status-icon]')!.getAttribute('data-task-manager-status-icon')).toBe('scheduled');
  });
});

describe('scheduled has its own hue (TM Mark II round 7 point 7)', () => {
  test('the scheduled token is neither the question yellow nor any other status color, and every theme gets it from tokens.css', async () => {
    const { STATUS_COLOR } = await import('./huddle-status');
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    expect(STATUS_COLOR.scheduled).toBe('var(--oc-scheduled)');
    const others = Object.entries(STATUS_COLOR).filter(([key]) => key !== 'scheduled').map(([, value]) => value);
    expect(others).not.toContain(STATUS_COLOR.scheduled);
    expect(readFileSync(resolve(process.cwd(), 'src/opscenter/tokens.css'), 'utf8')).toMatch(/--oc-scheduled:\s*var\(--oc-series-8\)/);
  });
});
