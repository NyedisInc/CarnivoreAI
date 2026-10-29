/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, section: string, position: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  items: [] as unknown[],
  groups: [] as unknown[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return server.prefs;
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 7, open: 7, review: 0, questions: 0, claude_seq: 0, unread: 0 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) {
        return { list: 'all', revision: 9, cursor: 9, groups: server.groups, items: server.items };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { sectionAreas } from './task-manager-status-areas';
import { statusSections } from './task-manager-status-sections';
import { statusFolds } from './task-manager-status-folds.svelte';
import type { HuddleItem, TaskManagerItemGroup } from './huddle-model';
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

async function mountBody(popout: boolean): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

const GROUPS = [
  { id: 8, list: 'all', name: 'widgets', position: 0, folded: false },
  { id: 7, list: 'all', name: 'huddle', position: 1, folded: false },
];

const MIXED = () => [
  mk(1, 'open', 0), mk(2, 'review', 1, { group: 7 }), mk(3, 'question', 2, { group: 7 }),
  mk(4, 'review', 3, { group: 8 }), mk(5, 'review', 4), mk(6, 'working', 5, { group: 8 }),
  mk(7, 'done', 6, { group: 8, state: 'done', status: 'done' }),
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.items = MIXED();
  server.groups = GROUPS;
  statusFolds.choices = {};
  huddle.selected = 'all';
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const as = (raw: unknown[]): HuddleItem[] => raw as HuddleItem[];
const asGroups = (raw: unknown[]): TaskManagerItemGroup[] => raw as TaskManagerItemGroup[];

describe('the model', () => {
  test('areas run in group order, no area last, empty areas are left out, hidden rows stay in `all`', () => {
    const review = statusSections(as(MIXED())).find((s) => s.key === 'review')!;
    const { subs, headed, drawn } = sectionAreas(review, asGroups(GROUPS), () => false);
    expect(headed).toBe(true);
    expect(subs.map((s) => [s.area, s.name, s.items.map((i) => i.id), s.start])).toEqual([[8, 'widgets', [4], 0], [7, 'huddle', [2], 1], [null, null, [5], 2]]);
    expect(drawn.map((i) => i.id)).toEqual([4, 2, 5]);
    const question = statusSections(as(MIXED())).find((s) => s.key === 'question')!;
    expect(sectionAreas(question, asGroups(GROUPS), () => false).subs.map((s) => s.area)).toEqual([7]);
  });

  test('a folded subsection draws no rows and the next one starts where it left off; no groups means no headers', () => {
    const review = statusSections(as(MIXED())).find((s) => s.key === 'review')!;
    const folded = sectionAreas(review, asGroups(GROUPS), (_k, area) => area === 8);
    expect(folded.subs.map((s) => [s.area, s.folded, s.start])).toEqual([[8, true, 0], [7, false, 0], [null, false, 1]]);
    expect(folded.drawn.map((i) => i.id)).toEqual([2, 5]);
    const whole = sectionAreas(review, [], () => false);
    expect(whole.headed).toBe(false);
    expect(whole.subs.map((s) => s.items.map((i) => i.id))).toEqual([[2, 4, 5]]);
  });
});

describe.each([['the sidebar', false], ['the pop-out', true]])('on screen, %s', (_name, popout) => {
  test('the headers read "status: area", in section order then group order, no area last, done folded', async () => {
    const host = await mountBody(popout);
    const sections = [...host.querySelectorAll('[data-task-manager-status-head] .hss-name')].map((n) => n.textContent);
    expect(sections).toEqual(['question for you', 'ready to review', 'working', 'open', 'done']);
    expect([...host.querySelectorAll('.hds-sub .hds-sub-name')].map((n) => n.textContent)).toEqual([
      'question for you: huddle', 'ready to review: widgets', 'ready to review: huddle', 'ready to review: no group', 'working: widgets',
      'open: no group',
    ]);
    expect(host.querySelector('[data-task-manager-status-section="done"] .hds-sub')).toBeNull();
    expect([...host.querySelectorAll('[data-task-manager-status-section="review"] .hds-count, [data-task-manager-status-section="review"] [data-huddle-item]')]
      .map((n) => n.getAttribute('data-huddle-item') ?? `count ${n.textContent}`)).toEqual(['count 1', '4', 'count 1', '2', 'count 1', '5']);
  });

  test('the status icon stays on the section header, and the sub-header is the area view\'s own element', async () => {
    const host = await mountBody(popout);
    expect(host.querySelector('[data-task-manager-status-head="review"] [data-task-manager-section-icon]')).not.toBeNull();
    const sub = host.querySelector<HTMLElement>('[data-task-manager-area-sub="8:review"], [data-task-manager-area-sub="status/8:review"]')!;
    expect(sub.classList.contains('hds-sub')).toBe(true);
    expect(sub.querySelector('.hds-sub-fold [data-task-manager-section-icon]')).not.toBeNull();
  });

  test('folding a subsection hides its rows only, and is remembered apart from the area view', async () => {
    const host = await mountBody(popout);
    host.querySelector<HTMLElement>('[data-task-manager-area-sub-fold="status/8:review"]')!.click();
    await settle();
    expect([...host.querySelectorAll('[data-task-manager-status-section="review"] [data-huddle-item]')].map((r) => r.getAttribute('data-huddle-item'))).toEqual(['2', '5']);
    expect(statusFolds.choices).toEqual({ 'status/8:review': true });
  });

  test('a list with no areas keeps whole sections and draws no sub-header', async () => {
    server.groups = [];
    server.items = MIXED().map((i) => ({ ...i, group: null }));
    await refreshTaskManager();
    const host = await mountBody(popout);
    expect(host.querySelector('.hds-sub')).toBeNull();
    expect([...host.querySelectorAll('[data-task-manager-status-section="review"] [data-huddle-item]')].map((r) => r.getAttribute('data-huddle-item'))).toEqual(['2', '4', '5']);
  });
});
