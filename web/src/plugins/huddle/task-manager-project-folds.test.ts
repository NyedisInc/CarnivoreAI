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

const GROUPS = () => [
  { list: 'all', name: null, project_id: null, revision: 3, groups: [], items: [mk(1, 'all', 'review')] },
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'question'), mk(12, '12', 'question'), mk(13, '12', 'review'), mk(14, '12', 'review'), mk(15, '12', 'review'),
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

const rows = (host: HTMLElement, list: string, section: string): string[] =>
  [...host.querySelectorAll<HTMLElement>(`[data-task-manager-status-list="${list}"] [data-task-manager-status-section="${section}"] [data-huddle-item]`)]
    .map((r) => r.dataset.huddleItem as string);

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('folding a status section folds it in THAT project only, and is remembered per project', async () => {
    const host = await mountBody(popout);
    expect(rows(host, '12', 'review')).toEqual(['13', '14', '15']);
    expect(rows(host, '18', 'review')).toEqual(['21']);
    host.querySelector<HTMLElement>('[data-task-manager-status-list="12"] [data-task-manager-status-fold="review"]')!.click();
    await settle();
    expect(rows(host, '12', 'review')).toEqual([]);
    expect(rows(host, '18', 'review')).toEqual(['21']);
    expect(rows(host, 'all', 'review')).toEqual(['1']);
    expect(JSON.parse(localStorage.getItem(FOLDS_KEY) as string)).toEqual({ [sectionFoldKey('12', 'review')]: true });
  });

  test('a project folds down to its title bar and count; its sections and rows are gone', async () => {
    const host = await mountBody(popout);
    expect(host.querySelector('[data-task-manager-status-list="12"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-project-count="12"]')!.textContent).toBe('6');
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-status-list="12"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-heading="12"]')!.textContent).toBe('alpha');
    expect(host.querySelector('[data-task-manager-project-count="12"]')!.textContent).toBe('6');
    expect(host.querySelector('[data-task-manager-project-fold="12"]')!.getAttribute('aria-expanded')).toBe('false');
    expect(host.querySelector('[data-task-manager-status-list="18"]')).not.toBeNull();
    expect(JSON.parse(localStorage.getItem(FOLDS_KEY) as string)).toEqual({ [projectFoldKey('12')]: true });
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-status-list="12"]')).not.toBeNull();
  });

  test('a folded project shows a chip per non-empty status with the rows\' icon and its count', async () => {
    const host = await mountBody(popout);
    const openChips = [...host.querySelectorAll<HTMLElement>('[data-task-manager-tail="12"] [data-filled]')].map((c) => [c.dataset.taskManagerTailSlot, c.querySelector('.hd-tail-n')!.textContent]);
    expect(openChips).toEqual([['question', '2'], ['review', '3'], ['working', '1']]);
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    const chips = [...host.querySelectorAll<HTMLElement>('[data-task-manager-tail="12"] [data-filled]')].map((c) => [
      c.dataset.taskManagerTailSlot, c.querySelector('.hd-tail-n')!.textContent, c.querySelector('[data-icon]')!.getAttribute('data-icon')])
      .filter((c) => c[0] !== 'question' && c[0] !== 'look' && c[0] !== 'info');
    expect(chips).toEqual([['review', '3', 'status-review'], ['working', '1', 'status-working']]);
    expect(chips.length).toBe(2);
    expect(host.querySelector('[data-task-manager-tail="12"] [data-task-manager-tail-slot="question"][data-filled] .hd-tail-n')!.textContent).toBe('2');
  });
});
