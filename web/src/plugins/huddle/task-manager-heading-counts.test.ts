/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

/** The one completed state these fixtures use (a fixture constant, never a literal in a test: the state names are being renamed, #1703). */
const COMPLETED = 'done';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, ...extra,
});
const doneWithInfo = (id: number, list: string, extra: Record<string, unknown> = {}) =>
  mk(id, list, { state: COMPLETED, status: COMPLETED, info_unread: 1, info_unseen: true, ...extra });

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
          { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'alpha', project_id: 12, items: 3, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '18', name: 'beta', project_id: 18, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (path.split('?')[0] === '/cplugs/huddle/aggregate') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, statusFolds } from './task-manager-status-folds.svelte';
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

async function mountBody(settings: Record<string, unknown>): Promise<HTMLElement> {
  server.prefs = { revision: 3, settings };
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

const infoMarked = (tail: Element | null): boolean => tail?.querySelector('[data-task-manager-tail-slot="info"][data-filled="on"]') != null;

beforeEach(() => {
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('a folded project bar', () => {
  const groups = () => [
    { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [mk(11, '12', { status: 'open' }), doneWithInfo(12, '12')] },
    { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', { status: 'open' })] },
  ];
  const projectTail = (host: HTMLElement): Element | null =>
    host.querySelector('[data-task-manager-project-fold="12"]')!.closest('[data-task-manager-level="project"]')!.querySelector('[data-task-manager-tail]');

  test.each([[false, true], [true, false]])('hide completed %s: the hidden item marks the folded bar: %s', async (hide, marked) => {
    server.groups = groups();
    statusFolds.choices = { [projectFoldKey('12')]: true };
    const host = await mountBody({ hideCompleted: hide, view: 'status' });
    expect(host.querySelector('[data-task-manager-project-fold="12"]')!.getAttribute('aria-expanded')).toBe('false');
    expect(infoMarked(projectTail(host))).toBe(marked);
  });
});

describe('a folded area bar', () => {
  const groups = () => [
    { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [{ id: 7, list: '12', name: 'ui', position: 1, folded: true }],
      items: [mk(11, '12', { status: 'open', group: 7 }), doneWithInfo(12, '12', { group: 7 })] },
    { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', { status: 'open' })] },
  ];

  test.each([[false, true], [true, false]])('hide completed %s: the hidden item marks the folded area: %s', async (hide, marked) => {
    server.groups = groups();
    const host = await mountBody({ hideCompleted: hide, view: 'area' });
    expect(infoMarked(host.querySelector('[data-task-manager-tail="7"]'))).toBe(marked);
  });
});
