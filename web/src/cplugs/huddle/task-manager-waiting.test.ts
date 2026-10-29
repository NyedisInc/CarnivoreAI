/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string, section: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
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
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'alpha', project_id: 12, items: 6, open: 6, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '18', name: 'beta', project_id: 18, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, sectionFoldKey, statusFolds } from './task-manager-status-folds.svelte';
import { waitingMarks } from './task-manager-waiting';
import { POST_KINDS } from './task-manager-posts';
import { SECTION_ICON } from './task-manager-status-sections';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
import { AGGREGATE } from './huddle-model';
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

/** alpha: 2 questions, a review with 2 unread looks and 1 unread info, a review with 1 unread info, 1 working. */
const GROUPS = () => [
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'question'), mk(12, '12', 'question'),
    mk(13, '12', 'review', { attention_unread: 2, attention_unseen: true, info_unread: 1, info_unseen: true }),
    mk(14, '12', 'review', { info_unread: 1, info_unseen: true }),
    mk(16, '12', 'working'),
  ] },
  { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review'), mk(22, '18', 'open')] },
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});


const marksIn = (el: Element | null): [string, string][] =>
  [...(el?.querySelectorAll<HTMLElement>('[data-task-manager-tail-slot][data-filled]') ?? [])].map((m) => [m.dataset.taskManagerTailSlot as string, m.querySelector('.hd-tail-n')!.textContent as string]);
const tailOf = (host: Element, id: string): Element | null => host.querySelector(`[data-task-manager-tail="${id}"]`);

test('the marks are counted from the items and wear the rows\' own icons and colors', () => {
  const items = GROUPS()[0]!.items as never[];
  expect(waitingMarks(items).map((m) => [m.kind, m.count])).toEqual([['question', 2], ['info', 2]]);
  expect(waitingMarks(items, ['question']).map((m) => m.kind)).toEqual(['info']);
  const [q, i] = waitingMarks(items);
  expect(q!.icon).toBe(SECTION_ICON.question);
  expect(i!.icon).toBe(POST_KINDS.info.icon);
  expect(i!.color).toBe(POST_KINDS.info.color);
  expect(waitingMarks([])).toEqual([]);
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('a folded project shows question and info with a count each (no look); open it and they are gone; beta has none', async () => {
    const host = await mountBody(popout);
    expect(marksIn(tailOf(host, '12')).map((m) => m[0])).not.toContain('look');
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="18"]')!.click();
    await settle();
    expect(marksIn(tailOf(host, '12')).slice(0, 2)).toEqual([['question', '2'], ['info', '2']]);
    expect(marksIn(tailOf(host, '18'))).toEqual([['review', '1'], ['open', '1']]);
    expect(marksIn(tailOf(host, '12')).map((m) => m[0])).toEqual(['question', 'info', 'review', 'working']);
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    expect(marksIn(tailOf(host, '12')).map((m) => m[0])).toEqual(['question', 'review', 'working']);
  });

  test('a folded status header shows the infos inside it (never looks), and an open one nothing', async () => {
    const host = await mountBody(popout);
    const head = (): Element | null => host.querySelector('[data-task-manager-status-list="12"] [data-task-manager-status-head="review"]');
    expect(marksIn(head())).toEqual([]);
    host.querySelector<HTMLElement>('[data-task-manager-status-list="12"] [data-task-manager-status-fold="review"]')!.click();
    await settle();
    expect(marksIn(head())).toEqual([['info', '2']]);
    host.querySelector<HTMLElement>('[data-task-manager-status-list="12"] [data-task-manager-status-fold="question"]')!.click();
    await settle();
    expect(marksIn(host.querySelector('[data-task-manager-status-list="12"] [data-task-manager-status-head="question"]'))).toEqual([]);
  });

  test('a folded status-in-area subheader shows its unread posts', async () => {
    const group = { id: 5, name: 'widgets', position: 0, folded: false };
    server.groups = [
      { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [group], items: [
        mk(13, '12', 'review', { group: 5, info_unread: 1, info_unseen: true }), mk(14, '12', 'working', { group: 5 }),
      ] },
    ];
    await refreshTaskManager();
    const host = await mountBody(popout);
    const fold = host.querySelector<HTMLElement>('[data-task-manager-area-sub-fold]');
    expect(fold).not.toBeNull();
    const review = [...host.querySelectorAll<HTMLElement>('[data-task-manager-area-sub-fold]')].find((b) => b.closest('li')!.querySelector('[data-task-manager-section-icon="status-review"]'));
    review!.click();
    await settle();
    const li = review!.closest('li')!;
    expect(marksIn(li)).toEqual([['info', '1']]);
  });
});

test('an area header (area view) shows its unread posts while folded', async () => {
  taskManagerPrefs.view = 'area';
  const group = { id: 5, name: 'widgets', position: 0, folded: true };
  server.groups = [
    { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [group], items: [
      mk(13, '12', 'review', { group: 5, attention_unread: 1, info_unread: 3 }), mk(14, '12', 'question', { group: 5 }),
    ] },
  ];
  await refreshTaskManager();
  const host = await mountBody(false);
  expect(marksIn(host.querySelector('[data-task-manager-section-head="5"]'))).toEqual([['question', '1'], ['info', '3']]);
  taskManagerPrefs.view = 'status';
});
